"""Native WireGuard interface management for a NexusPanel node (Phase 11.2).

The panel pushes a declarative spec (interface keys, listen port, address and
the full peer list) and reads back per-peer transfer counters. Those counters
are mapped ``public_key -> User.id`` on the panel and folded into the single
``User.used_traffic`` — see ``docs/accounting-contract.md``.

The module is deliberately self-contained (stdlib only) and the command runner
is injectable so the config rendering and ``wg show transfer`` parsing are unit
testable without root or a real WireGuard interface.
"""
import ipaddress
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

logger = logging.getLogger("nexus-node-wg")


@dataclass
class WireGuardPeer:
    public_key: str
    allowed_ips: List[str]
    preshared_key: Optional[str] = None


@dataclass
class WireGuardSpec:
    interface: str
    listen_port: int
    private_key: str
    address: List[str]                      # interface CIDRs, e.g. ["10.10.0.1/24"]
    peers: List[WireGuardPeer] = field(default_factory=list)
    mtu: Optional[int] = None
    # AmneziaWG obfuscation params (Jc/Jmin/...). When set and amneziawg-go is
    # installed, the manager uses awg syncconf instead of plain wg.
    amnezia: Optional[dict] = None

    @classmethod
    def from_dict(cls, data: dict) -> "WireGuardSpec":
        peers = [
            WireGuardPeer(
                public_key=p["public_key"],
                allowed_ips=list(p.get("allowed_ips") or []),
                preshared_key=p.get("preshared_key") or None,
            )
            for p in (data.get("peers") or [])
        ]
        address = data.get("address")
        if isinstance(address, str):
            address = [address]
        return cls(
            interface=data["interface"],
            listen_port=int(data["listen_port"]),
            private_key=data["private_key"],
            address=list(address or []),
            peers=peers,
            mtu=int(data["mtu"]) if data.get("mtu") else None,
            amnezia=data.get("amnezia") or None,
        )


def parse_transfer(output: str) -> Dict[str, dict]:
    """Parse ``wg show <iface> transfer`` output.

    Each line is ``<public_key>\\t<rx_bytes>\\t<tx_bytes>``. Returns a map of
    ``public_key -> {"rx": int, "tx": int}``.
    """
    result: Dict[str, dict] = {}
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t") if "\t" in line else line.split()
        if len(parts) < 3:
            continue
        public_key, rx, tx = parts[0], parts[1], parts[2]
        try:
            result[public_key] = {"rx": int(rx), "tx": int(tx)}
        except ValueError:
            continue
    return result


def render_syncconf(spec: WireGuardSpec, *, include_amnezia: Optional[bool] = None) -> str:
    """Render the stripped config consumed by ``wg``/``awg syncconf``.

    Interface key/port plus peers; addresses and MTU are applied via ``ip``
    separately. AmneziaWG params are only included when the server runs AWG.
    """
    show_awg = include_amnezia if include_amnezia is not None else bool(spec.amnezia)
    lines = [
        "[Interface]",
        f"ListenPort = {spec.listen_port}",
        f"PrivateKey = {spec.private_key}",
    ]
    if show_awg and spec.amnezia:
        for key in ("Jc", "Jmin", "Jmax", "S1", "S2", "H1", "H2", "H3", "H4"):
            if key in spec.amnezia:
                lines.append(f"{key} = {spec.amnezia[key]}")
    for peer in spec.peers:
        lines.append("")
        lines.append("[Peer]")
        lines.append(f"PublicKey = {peer.public_key}")
        if peer.preshared_key:
            lines.append(f"PresharedKey = {peer.preshared_key}")
        allowed = ", ".join(peer.allowed_ips) if peer.allowed_ips else ""
        lines.append(f"AllowedIPs = {allowed}")
    return "\n".join(lines) + "\n"


def subnets_from_specs(specs: Sequence[WireGuardSpec]) -> List[str]:
    """Derive client NAT subnets (e.g. 10.10.0.0/24) from interface addresses."""
    subnets: List[str] = []
    seen: set[str] = set()
    for spec in specs:
        for addr in spec.address:
            try:
                net = str(ipaddress.ip_network(addr, strict=False))
            except ValueError:
                continue
            if net not in seen:
                seen.add(net)
                subnets.append(net)
    return subnets


def ensure_egress_forwarding(
    specs: Sequence[WireGuardSpec],
    run: Optional[Callable] = None,
) -> None:
    """MASQUERADE + FORWARD so WG clients can reach the internet on host network.

    Idempotent: skips rules that already exist. No-op when iptables or the
    default route is unavailable (unit tests / minimal containers).
    """
    if not shutil.which("iptables"):
        return
    runner = run or WireGuardManager._default_run
    route = runner(["ip", "route", "get", "8.8.8.8"], check=False)
    if getattr(route, "returncode", 1) != 0:
        return
    parts = (getattr(route, "stdout", "") or "").split()
    try:
        dev_idx = parts.index("dev")
        outbound = parts[dev_idx + 1]
    except (ValueError, IndexError):
        return

    subnets = subnets_from_specs(specs)
    interfaces = sorted({spec.interface for spec in specs})

    def _ensure(table: Optional[str], args: List[str]) -> None:
        check = ["iptables"]
        add = ["iptables"]
        if table:
            check.extend(["-t", table])
            add.extend(["-t", table])
        check.extend(["-C", *args])
        add.extend(["-A", *args])
        if getattr(runner(check, check=False), "returncode", 1) != 0:
            runner(add, check=False)

    for subnet in subnets:
        _ensure("nat", ["POSTROUTING", "-s", subnet, "-o", outbound, "-j", "MASQUERADE"])
    for iface in interfaces:
        _ensure(None, ["FORWARD", "-i", iface, "-j", "ACCEPT"])
        _ensure(
            None,
            [
                "FORWARD",
                "-o",
                iface,
                "-m",
                "conntrack",
                "--ctstate",
                "RELATED,ESTABLISHED",
                "-j",
                "ACCEPT",
            ],
        )
    logger.info(
        "Ensured WG egress (ifaces=%s, subnets=%s, out=%s)",
        interfaces,
        subnets,
        outbound,
    )


class WireGuardManager:
    """Thin wrapper over ``wg``/``awg`` + ``ip`` for declarative interface management."""

    def __init__(self, run: Optional[Callable] = None):
        self._run = run or self._default_run

    @staticmethod
    def _default_run(cmd, input=None, check=True):
        return subprocess.run(
            cmd, input=input, text=True, capture_output=True, check=check
        )

    def available(self) -> bool:
        return shutil.which("wg") is not None and shutil.which("ip") is not None

    def amnezia_available(self) -> bool:
        """True when AWG can be applied (kernel ``awg`` and/or userspace engine)."""
        return shutil.which("ip") is not None and (
            shutil.which("awg") is not None or shutil.which("amneziawg-go") is not None
        )

    def _use_amnezia(self, spec: WireGuardSpec) -> bool:
        return bool(spec.amnezia) and self.amnezia_available()

    def _wg_bin(self, spec: WireGuardSpec) -> str:
        if self._use_amnezia(spec) and shutil.which("awg"):
            return "awg"
        return "wg"

    def _interface_is_userspace_awg(self, interface: str) -> bool:
        needle = f"amneziawg-go {interface}"
        if shutil.which("pgrep"):
            result = self._run(["pgrep", "-f", needle], check=False)
            return getattr(result, "returncode", 1) == 0
        try:
            for pid in os.listdir("/proc"):
                if not pid.isdigit():
                    continue
                with open(f"/proc/{pid}/cmdline", "rb") as fh:
                    cmd = fh.read().replace(b"\0", b" ").decode(errors="ignore")
                if needle in cmd:
                    return True
        except OSError:
            return False
        return False

    def interface_exists(self, interface: str) -> bool:
        result = self._run(["ip", "link", "show", interface], check=False)
        return getattr(result, "returncode", 1) == 0

    def ensure_interface(self, spec: WireGuardSpec) -> None:
        want_awg = self._use_amnezia(spec)
        exists = self.interface_exists(spec.interface)
        is_awg = self._interface_is_userspace_awg(spec.interface) if exists else False
        userspace_awg = want_awg and os.path.exists("/dev/net/tun") and shutil.which("amneziawg-go")

        if userspace_awg and not is_awg:
            if exists:
                self.teardown(spec.interface)
            self._run(["amneziawg-go", spec.interface], check=False)
        elif want_awg and not is_awg and not exists and shutil.which("awg"):
            self._run(["ip", "link", "add", "dev", spec.interface, "type", "wireguard"], check=False)
        elif not want_awg and is_awg:
            self.teardown(spec.interface)
            self._run(["ip", "link", "add", "dev", spec.interface, "type", "wireguard"])
        elif not want_awg and not exists:
            self._run(["ip", "link", "add", "dev", spec.interface, "type", "wireguard"])
        # Make addresses declarative: flush then re-add.
        self._run(["ip", "address", "flush", "dev", spec.interface], check=False)
        for addr in spec.address:
            self._run(["ip", "address", "add", addr, "dev", spec.interface], check=False)
        if spec.mtu:
            self._run(["ip", "link", "set", "mtu", str(spec.mtu), "dev", spec.interface], check=False)
        self._run(["ip", "link", "set", "up", "dev", spec.interface], check=False)

    def apply_specs(self, specs: List[WireGuardSpec]) -> None:
        for spec in specs:
            self.apply(spec)
        ensure_egress_forwarding(specs, run=self._run)

    def apply(self, spec: WireGuardSpec) -> None:
        """Bring the interface to the desired state (idempotent)."""
        use_awg = self._use_amnezia(spec)
        if spec.amnezia and not use_awg:
            logger.warning(
                "AmneziaWG params configured but amneziawg-go is unavailable; "
                "applying plain WireGuard on %s",
                spec.interface,
            )
        self.ensure_interface(spec)
        conf = render_syncconf(spec, include_amnezia=use_awg)
        wg = self._wg_bin(spec)
        self._run([wg, "syncconf", spec.interface, "/dev/stdin"], input=conf)
        mode = "AmneziaWG" if use_awg else "WireGuard"
        logger.info("Applied %s spec to %s (%d peers)", mode, spec.interface, len(spec.peers))

    def get_transfer(self, interface: str) -> Dict[str, dict]:
        wg = "awg" if self._interface_is_userspace_awg(interface) or shutil.which("awg") else "wg"
        result = self._run([wg, "show", interface, "transfer"], check=False)
        if getattr(result, "returncode", 1) != 0:
            return {}
        return parse_transfer(getattr(result, "stdout", "") or "")

    def teardown(self, interface: str) -> None:
        if self.interface_exists(interface):
            self._run(["ip", "link", "del", "dev", interface], check=False)
            logger.info("Tore down WireGuard interface %s", interface)
