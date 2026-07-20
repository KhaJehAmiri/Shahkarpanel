"""WireGuard auto-scale runtime on the node agent.

Creates additional kernel interfaces (wg0, wg2, …) when a subnet fills up,
hot-adds peers via ``wg set`` (no restart), and exposes ``wg show all dump``
for monitoring. AWG listeners stay on the legacy ``WireGuardManager`` path.
"""
import ipaddress
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

try:
    from wireguard import ephemeral_psk_file
except ImportError:
    from node.wireguard import ephemeral_psk_file

logger = logging.getLogger("nexus-node-wg-autoscale")

# Soft-disable: keep the peer entry but black-hole traffic. Prefer a host
# loopback /32 — some ``wg``/``awg`` builds reject ``0.0.0.0/32``.
DISABLED_ALLOWED_IPS = "127.0.0.1/32"
DISABLED_ALLOWED_IPS_FALLBACK = "0.0.0.0/32"
CONF_DIR = "/etc/wireguard"


@dataclass
class InterfaceSpec:
    name: str
    listen_port: int
    private_key: str
    public_key: str
    subnet: str
    mtu: int = 1420

    @classmethod
    def from_dict(cls, data: dict) -> "InterfaceSpec":
        return cls(
            name=data["name"],
            listen_port=int(data["listen_port"]),
            private_key=data["private_key"],
            public_key=data["public_key"],
            subnet=data["subnet"],
            mtu=int(data.get("mtu") or 1420),
        )


def server_address(subnet: str) -> str:
    network = ipaddress.ip_network(subnet, strict=False)
    host = next(network.hosts(), None)
    if host is None:
        raise ValueError(f"subnet {subnet!r} has no usable host")
    return f"{host}/{network.prefixlen}"


def render_interface_conf(spec: InterfaceSpec) -> str:
    lines = [
        "[Interface]",
        f"PrivateKey = {spec.private_key}",
        f"Address = {server_address(spec.subnet)}",
        f"ListenPort = {spec.listen_port}",
        f"MTU = {spec.mtu}",
        "",
    ]
    return "\n".join(lines)


class WireGuardAutoScale:
    """Hot-add peers and spin up new interfaces without service restarts."""

    def __init__(self, run: Optional[Callable] = None):
        self._run = run or self._default_run

    @staticmethod
    def _default_run(cmd, input=None, check=True):
        return subprocess.run(
            cmd, input=input, text=True, capture_output=True, check=check
        )

    def available(self) -> bool:
        return self._wg_bin() is not None and shutil.which("ip") is not None

    @staticmethod
    def _wg_bin() -> Optional[str]:
        """Prefer ``awg`` when present (AmneziaWG nodes), else plain ``wg``."""
        return shutil.which("awg") or shutil.which("wg")

    def interface_exists(self, name: str) -> bool:
        result = self._run(["ip", "link", "show", name], check=False)
        return getattr(result, "returncode", 1) == 0

    def create_interface(self, spec: InterfaceSpec) -> None:
        """Write conf, ``wg-quick up``, and ``systemctl enable`` for a new iface."""
        if not self.available():
            raise RuntimeError("wg/ip not available on node")

        os.makedirs(CONF_DIR, mode=0o700, exist_ok=True)
        conf_path = os.path.join(CONF_DIR, f"{spec.name}.conf")
        conf_body = render_interface_conf(spec)
        with open(conf_path, "w", encoding="utf-8") as fh:
            fh.write(conf_body)
        os.chmod(conf_path, 0o600)

        if self.interface_exists(spec.name):
            logger.info("Interface %s already up; skipping wg-quick up", spec.name)
        elif shutil.which("wg-quick"):
            result = self._run(["wg-quick", "up", spec.name], check=False)
            if getattr(result, "returncode", 1) != 0:
                stderr = getattr(result, "stderr", "") or ""
                raise RuntimeError(f"wg-quick up {spec.name} failed: {stderr.strip()}")
        else:
            self._bring_up_manual(spec)

        if shutil.which("systemctl"):
            unit = f"wg-quick@{spec.name}.service"
            self._run(["systemctl", "enable", unit], check=False)

        try:
            from wireguard import WireGuardSpec, ensure_egress_forwarding
        except ImportError:
            from node.wireguard import WireGuardSpec, ensure_egress_forwarding

        wg_spec = WireGuardSpec(
            interface=spec.name,
            listen_port=spec.listen_port,
            private_key=spec.private_key,
            address=[server_address(spec.subnet)],
            peers=[],
            mtu=spec.mtu,
        )
        ensure_egress_forwarding([wg_spec], run=self._run)
        logger.info(
            "Created auto-scale interface %s (port=%s subnet=%s)",
            spec.name,
            spec.listen_port,
            spec.subnet,
        )

    def _bring_up_manual(self, spec: InterfaceSpec) -> None:
        self._run(["ip", "link", "add", "dev", spec.name, "type", "wireguard"], check=False)
        self._run(
            ["wg", "set", spec.name, "private-key", "/dev/stdin"],
            input=spec.private_key + "\n",
            check=True,
        )
        self._run(["wg", "set", spec.name, "listen-port", str(spec.listen_port)], check=False)
        self._run(
            ["ip", "address", "add", server_address(spec.subnet), "dev", spec.name],
            check=False,
        )
        if spec.mtu:
            self._run(["ip", "link", "set", "mtu", str(spec.mtu), "dev", spec.name], check=False)
        self._run(["ip", "link", "set", "up", "dev", spec.name], check=False)

    def hot_add_peer(
        self,
        interface: str,
        public_key: str,
        allowed_ips: str,
        *,
        preshared_key: Optional[str] = None,
    ) -> None:
        """Add or update a peer via ``wg``/``awg set`` without restarting the interface."""
        wg = self._wg_bin()
        if not wg:
            raise RuntimeError("wg/awg not available on node")
        if not self.interface_exists(interface):
            raise RuntimeError(f"interface {interface} does not exist")
        cmd = [wg, "set", interface, "peer", public_key, "allowed-ips", allowed_ips]

        def _run_set(extra: Optional[list] = None):
            full = cmd + (extra or [])
            result = self._run(full, check=False)
            if getattr(result, "returncode", 1) != 0:
                err = (getattr(result, "stderr", "") or getattr(result, "stdout", "") or "").strip()
                raise RuntimeError(err or f"{wg} set failed for {interface}")

        if preshared_key:
            with ephemeral_psk_file(preshared_key) as psk_path:
                _run_set(["preshared-key", psk_path])
        else:
            _run_set()

    def toggle_peer(
        self,
        interface: str,
        public_key: str,
        *,
        active: bool,
        allowed_ips: str,
        preshared_key: Optional[str] = None,
    ) -> None:
        """Enable or soft-disable a peer (keep config, block traffic when inactive)."""
        if active:
            self.hot_add_peer(
                interface,
                public_key,
                allowed_ips,
                preshared_key=preshared_key,
            )
            return
        # Soft-disable: try loopback /32 first, then legacy 0.0.0.0/32.
        last_err: Optional[Exception] = None
        for ips in (DISABLED_ALLOWED_IPS, DISABLED_ALLOWED_IPS_FALLBACK):
            try:
                self.hot_add_peer(
                    interface,
                    public_key,
                    ips,
                    preshared_key=preshared_key,
                )
                return
            except Exception as exc:
                last_err = exc
        if last_err:
            raise last_err

    def show_dump_all(self) -> List[dict]:
        """Parse ``wg show all dump`` into a list of peer rows."""
        result = self._run(["wg", "show", "all", "dump"], check=False)
        if getattr(result, "returncode", 1) != 0:
            return []
        rows: List[dict] = []
        for line in (getattr(result, "stdout", "") or "").splitlines():
            parts = line.split("\t")
            if len(parts) < 8:
                continue
            iface, pubkey, psk, endpoint, allowed, _latest, rx, tx = parts[:8]
            if iface.startswith("interface:"):
                continue
            rows.append(
                {
                    "interface": iface,
                    "public_key": pubkey,
                    "preshared_key": None if psk == "(none)" else psk,
                    "endpoint": None if endpoint == "(none)" else endpoint,
                    "allowed_ips": allowed,
                    "rx_bytes": int(rx) if rx.isdigit() else 0,
                    "tx_bytes": int(tx) if tx.isdigit() else 0,
                }
            )
        return rows

    def get_transfer(self, interface: str) -> Dict[str, dict]:
        try:
            from wireguard import parse_transfer
        except ImportError:
            from node.wireguard import parse_transfer

        result = self._run(["wg", "show", interface, "transfer"], check=False)
        if getattr(result, "returncode", 1) != 0:
            return {}
        return parse_transfer(getattr(result, "stdout", "") or "")
