"""Linux traffic shaping for per-client speed limits (WireGuard + sing-box ports).

Uses HTB + fq_codel (and IFB for ingress) so limits are enforced smoothly without
hard policer drops that hurt latency and QUIC/Hysteria2 quality.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("nexus-node-speed-limit")

RunFn = Callable[..., subprocess.CompletedProcess]
IFB_DEV = "ifb0"


def _tc_binary() -> Optional[str]:
    for candidate in (shutil.which("tc"), "/usr/sbin/tc", "/sbin/tc"):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _default_run(cmd: List[str], check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, text=True, capture_output=True, check=check)


def _mbps_to_rate(mbps: int) -> str:
    return f"{max(int(mbps), 1)}mbit"


def _htb_burst(mbps: int) -> Tuple[str, str]:
    """Return (burst, cburst) sized for ~500ms at the capped rate (QUIC-friendly)."""
    bytes_per_sec = max(int(mbps), 1) * 125_000
    burst = min(max(bytes_per_sec // 2, 65_536), 1_250_000)
    token = f"{burst}b"
    return token, token


def _htb_rates(mbps: int) -> Tuple[str, str]:
    """Return (rate, ceil) with a small headroom band so fq_codel absorbs micro-bursts."""
    cap = max(int(mbps), 1)
    floor = max(int(cap * 0.92), 1)
    if floor >= cap:
        return f"{cap}mbit", f"{cap}mbit"
    return f"{floor}mbit", f"{cap}mbit"


@dataclass
class PeerLimit:
    address: str
    up_mbps: int
    down_mbps: int


@dataclass
class PortLimit:
    port: int
    up_mbps: int
    down_mbps: int
    protocol: Optional[str] = None


class SpeedLimitManager:
    """Apply HTB + fq_codel shaping on WG interfaces and on the default NIC by port."""

    ROOT_HANDLE = "1:"
    ROOT_CLASS = "1:1"
    DEFAULT_MINOR = 9999
    DEFAULT_CLASS = "1:9999"

    def __init__(self, run: Optional[RunFn] = None):
        self._run = run or _default_run
        self._wg_limits: Dict[str, List[PeerLimit]] = {}
        self._port_limits: List[PortLimit] = []

    def available(self) -> bool:
        return _tc_binary() is not None

    def apply_wireguard(self, interface: str, limits: List[PeerLimit]) -> None:
        self._wg_limits[interface] = list(limits or [])
        if not limits:
            self._clear_shaping(interface)
            return
        if not self.available():
            logger.warning("tc not installed; skipping WireGuard speed limits on %s", interface)
            return
        self._clear_shaping(interface)
        self._setup_htb_root(interface)
        class_id = 10
        for lim in limits:
            host = lim.address.split("/")[0]
            up = max(int(lim.up_mbps or lim.down_mbps or 1), 1)
            down = max(int(lim.down_mbps or lim.up_mbps or 1), 1)
            if up == down:
                cid = f"1:{class_id}"
                self._add_htb_leaf(interface, cid, down)
                self._tc(
                    [
                        "filter", "add", "dev", interface, "parent", self.ROOT_HANDLE,
                        "protocol", "ip", "prio", "1", "u32", "match", "ip", "dst", host,
                        "flowid", cid,
                    ]
                )
                self._tc(
                    [
                        "filter", "add", "dev", interface, "parent", self.ROOT_HANDLE,
                        "protocol", "ip", "prio", "1", "u32", "match", "ip", "src", host,
                        "flowid", cid,
                    ]
                )
                class_id += 1
            else:
                down_cid = f"1:{class_id}"
                class_id += 1
                up_cid = f"1:{class_id}"
                class_id += 1
                self._add_htb_leaf(interface, down_cid, down)
                self._add_htb_leaf(interface, up_cid, up)
                self._tc(
                    [
                        "filter", "add", "dev", interface, "parent", self.ROOT_HANDLE,
                        "protocol", "ip", "prio", "1", "u32", "match", "ip", "dst", host,
                        "flowid", down_cid,
                    ]
                )
                self._tc(
                    [
                        "filter", "add", "dev", interface, "parent", self.ROOT_HANDLE,
                        "protocol", "ip", "prio", "1", "u32", "match", "ip", "src", host,
                        "flowid", up_cid,
                    ]
                )

    def apply_ports(self, limits: List[PortLimit]) -> None:
        merged = _merge_port_limits(limits)
        self._port_limits = merged
        if not merged:
            return
        if not self.available():
            logger.warning("tc not installed; skipping sing-box port speed limits")
            return
        iface = self._default_iface()
        if not iface:
            logger.warning("no default route interface; skipping port speed limits")
            return
        self._clear_shaping(iface)
        self._clear_shaping(IFB_DEV)
        self._ensure_ifb()
        self._tune_quic_stack()
        self._setup_htb_root(iface)
        self._setup_htb_root(IFB_DEV)
        self._setup_ingress(iface)
        class_id = 10
        for lim in merged:
            down_cid = f"1:{class_id}"
            class_id += 1
            up_cid = f"1:{class_id}"
            class_id += 1
            down = max(int(lim.down_mbps or lim.up_mbps or 1), 1)
            up = max(int(lim.up_mbps or lim.down_mbps or 1), 1)
            proto = (lim.protocol or "").lower() or None
            # Client download: egress on public iface, match service source port.
            self._add_htb_leaf(iface, down_cid, down)
            self._tc(
                [
                    "filter", "add", "dev", iface, "parent", self.ROOT_HANDLE,
                    "protocol", "ip", "prio", "1", "u32",
                    *self._protocol_match(proto),
                    "match", "ip", "sport", str(lim.port), "0xffff", "flowid", down_cid,
                ]
            )
            # Client upload: redirect ingress to IFB and shape there (no policer drops).
            self._add_htb_leaf(IFB_DEV, up_cid, up)
            self._tc(
                [
                    "filter", "add", "dev", iface, "parent", "ffff:",
                    "protocol", "ip", "prio", "1", "u32",
                    *self._protocol_match(proto),
                    "match", "ip", "dport", str(lim.port), "0xffff",
                    "action", "mirred", "egress", "redirect", "dev", IFB_DEV,
                ]
            )
            self._tc(
                [
                    "filter", "add", "dev", IFB_DEV, "parent", self.ROOT_HANDLE,
                    "protocol", "ip", "prio", "1", "u32",
                    *self._protocol_match(proto),
                    "match", "ip", "dport", str(lim.port), "0xffff", "flowid", up_cid,
                ]
            )

    def _ensure_ifb(self) -> None:
        modprobe = shutil.which("modprobe") or (
            "/sbin/modprobe" if os.path.isfile("/sbin/modprobe") else None
        )
        if modprobe:
            self._run([modprobe, "ifb"], check=False)
        ip = shutil.which("ip") or "/usr/bin/ip"
        self._run([ip, "link", "add", IFB_DEV, "type", "ifb"], check=False)
        self._run([ip, "link", "set", IFB_DEV, "up"], check=False)

    def _add_htb_leaf(self, interface: str, classid: str, mbps: int) -> None:
        rate, ceil = _htb_rates(mbps)
        burst, cburst = _htb_burst(mbps)
        self._tc(
            [
                "class", "add", "dev", interface, "parent", self.ROOT_CLASS,
                "classid", classid, "htb", "rate", rate, "ceil", ceil,
                "burst", burst, "cburst", cburst,
            ]
        )
        self._add_fq_codel(interface, classid)

    def _add_fq_codel(self, interface: str, classid: str) -> None:
        args = [
            "qdisc", "add", "dev", interface, "parent", classid,
            "fq_codel", "limit", "2048", "flows", "1024",
            "target", "5ms", "interval", "100ms", "memory_limit", "64Mb",
        ]
        result = self._tc(args + ["ecn"], ignore_errors=True, capture=True)
        if result and result.returncode != 0:
            self._tc(args, ignore_errors=True)

    @staticmethod
    def _protocol_match(proto: Optional[str]) -> List[str]:
        if proto == "udp":
            return ["match", "ip", "protocol", "17", "0xff"]
        if proto == "tcp":
            return ["match", "ip", "protocol", "6", "0xff"]
        return []

    def _tune_quic_stack(self) -> None:
        tune_udp_quic_stack(run=self._run)

    def _default_iface(self) -> Optional[str]:
        try:
            with open("/proc/net/route", "r", encoding="utf-8") as fh:
                for line in fh.readlines()[1:]:
                    parts = line.strip().split()
                    if len(parts) >= 2 and parts[1] == "00000000":
                        return parts[0]
        except Exception:
            pass
        try:
            out = self._run(["ip", "route", "get", "1.1.1.1"], check=False)
            parts = (out.stdout or "").split()
            if "dev" in parts:
                return parts[parts.index("dev") + 1]
        except Exception:
            pass
        return None

    def _clear_shaping(self, interface: str) -> None:
        self._tc(["qdisc", "del", "dev", interface, "root"], ignore_errors=True)
        self._tc(["qdisc", "del", "dev", interface, "ingress"], ignore_errors=True)

    def _setup_htb_root(self, interface: str) -> None:
        self._tc(
            [
                "qdisc", "replace", "dev", interface, "root", "handle", self.ROOT_HANDLE,
                "htb", "default", str(self.DEFAULT_MINOR),
            ]
        )
        self._tc(
            [
                "class", "add", "dev", interface, "parent", self.ROOT_HANDLE,
                "classid", self.ROOT_CLASS, "htb", "rate", "1000mbit", "ceil", "1000mbit",
            ],
            ignore_errors=True,
        )
        self._tc(
            [
                "class", "add", "dev", interface, "parent", self.ROOT_CLASS,
                "classid", self.DEFAULT_CLASS, "htb", "rate", "1000mbit", "ceil", "1000mbit",
            ],
            ignore_errors=True,
        )

    def _setup_ingress(self, interface: str) -> None:
        self._tc(["qdisc", "add", "dev", interface, "handle", "ffff:", "ingress"], ignore_errors=True)

    def _tc(self, args: List[str], *, ignore_errors: bool = False, capture: bool = False):
        tc_bin = _tc_binary()
        if not tc_bin:
            return None
        cmd = [tc_bin, *args]
        try:
            result = self._run(cmd, check=False)
            if result.returncode != 0 and not ignore_errors:
                err = (result.stderr or result.stdout or "").strip()
                if "File exists" in err or "already exists" in err:
                    return result
                logger.warning("tc %s failed: %s", " ".join(args), err)
            return result
        except Exception as exc:
            if not ignore_errors:
                logger.warning("tc failed: %s", exc)
            return None


def tune_udp_quic_stack(*, run: Optional[RunFn] = None) -> None:
    """Raise UDP/QUIC kernel buffers for Hysteria2/TUIC (always safe to call).

    Previously this only ran inside ``apply_ports`` when speed-tier shaping was
    active, so unlimited users kept tiny OS defaults. Call on node startup and
    whenever sing-box (Hy2/TUIC) is applied — not only when tc shaping runs.
    """
    runner = run or _default_run
    sysctl = shutil.which("sysctl") or "/usr/sbin/sysctl"
    for key, value in UDP_QUIC_SYSCTL.items():
        runner([sysctl, "-w", f"{key}={value}"], check=False)


# Keep in sync with ``app.xray.network_defaults.HOST_SYSCTL_TUNING`` buffer keys.
UDP_QUIC_SYSCTL: dict[str, str] = {
    "net.core.rmem_max": "26214400",
    "net.core.wmem_max": "26214400",
    "net.core.netdev_max_backlog": "250000",
    "net.ipv4.udp_mem": "65536 131072 262144",
}


def _merge_port_limits(limits: List[PortLimit]) -> List[PortLimit]:
    merged: Dict[int, PortLimit] = {}
    for lim in limits or []:
        port = int(lim.port)
        cur = merged.get(port)
        if cur is None:
            merged[port] = PortLimit(
                port=port,
                up_mbps=max(int(lim.up_mbps or 0), 1),
                down_mbps=max(int(lim.down_mbps or 0), 1),
                protocol=lim.protocol,
            )
        else:
            merged[port] = PortLimit(
                port=port,
                up_mbps=max(cur.up_mbps, int(lim.up_mbps or 0)),
                down_mbps=max(cur.down_mbps, int(lim.down_mbps or 0)),
                protocol=cur.protocol or lim.protocol,
            )
    return list(merged.values())


def peer_limits_from_spec(spec: dict) -> List[PeerLimit]:
    out: List[PeerLimit] = []
    for peer in spec.get("peers") or []:
        up = peer.get("speed_limit_up")
        down = peer.get("speed_limit_down")
        if not up and not down:
            continue
        for addr in peer.get("allowed_ips") or []:
            out.append(
                PeerLimit(
                    address=str(addr),
                    up_mbps=int(up or down or 1),
                    down_mbps=int(down or up or 1),
                )
            )
    return out


def port_limits_from_spec(spec: dict) -> List[PortLimit]:
    out: List[PortLimit] = []
    for item in spec.get("traffic_limits") or []:
        up = int(item.get("up_mbps") or 0)
        down = int(item.get("down_mbps") or 0)
        if not up and not down:
            continue
        out.append(
            PortLimit(
                port=int(item["port"]),
                up_mbps=up or down,
                down_mbps=down or up,
                protocol=str(item.get("protocol") or "").lower() or None,
            )
        )
    return out
