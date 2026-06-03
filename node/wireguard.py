"""Native WireGuard interface management for a NexusPanel node (Phase 11.2).

The panel pushes a declarative spec (interface keys, listen port, address and
the full peer list) and reads back per-peer transfer counters. Those counters
are mapped ``public_key -> User.id`` on the panel and folded into the single
``User.used_traffic`` — see ``docs/accounting-contract.md``.

The module is deliberately self-contained (stdlib only) and the command runner
is injectable so the config rendering and ``wg show transfer`` parsing are unit
testable without root or a real WireGuard interface.
"""
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

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


def render_syncconf(spec: WireGuardSpec) -> str:
    """Render the stripped config consumed by ``wg syncconf`` (interface key /
    port plus peers; addresses and MTU are applied via ``ip`` separately)."""
    lines = [
        "[Interface]",
        f"ListenPort = {spec.listen_port}",
        f"PrivateKey = {spec.private_key}",
    ]
    for peer in spec.peers:
        lines.append("")
        lines.append("[Peer]")
        lines.append(f"PublicKey = {peer.public_key}")
        if peer.preshared_key:
            lines.append(f"PresharedKey = {peer.preshared_key}")
        allowed = ", ".join(peer.allowed_ips) if peer.allowed_ips else ""
        lines.append(f"AllowedIPs = {allowed}")
    return "\n".join(lines) + "\n"


class WireGuardManager:
    """Thin wrapper over ``wg`` / ``ip`` for declarative interface management."""

    def __init__(self, run: Optional[Callable] = None):
        self._run = run or self._default_run

    @staticmethod
    def _default_run(cmd, input=None, check=True):
        return subprocess.run(
            cmd, input=input, text=True, capture_output=True, check=check
        )

    def available(self) -> bool:
        return shutil.which("wg") is not None and shutil.which("ip") is not None

    def interface_exists(self, interface: str) -> bool:
        result = self._run(["ip", "link", "show", interface], check=False)
        return getattr(result, "returncode", 1) == 0

    def ensure_interface(self, spec: WireGuardSpec) -> None:
        if not self.interface_exists(spec.interface):
            self._run(["ip", "link", "add", "dev", spec.interface, "type", "wireguard"])
        # Make addresses declarative: flush then re-add.
        self._run(["ip", "address", "flush", "dev", spec.interface], check=False)
        for addr in spec.address:
            self._run(["ip", "address", "add", addr, "dev", spec.interface], check=False)
        if spec.mtu:
            self._run(["ip", "link", "set", "mtu", str(spec.mtu), "dev", spec.interface], check=False)
        self._run(["ip", "link", "set", "up", "dev", spec.interface], check=False)

    def apply(self, spec: WireGuardSpec) -> None:
        """Bring the interface to the desired state (idempotent)."""
        self.ensure_interface(spec)
        conf = render_syncconf(spec)
        self._run(["wg", "syncconf", spec.interface, "/dev/stdin"], input=conf)
        logger.info("Applied WireGuard spec to %s (%d peers)", spec.interface, len(spec.peers))

    def get_transfer(self, interface: str) -> Dict[str, dict]:
        result = self._run(["wg", "show", interface, "transfer"], check=False)
        if getattr(result, "returncode", 1) != 0:
            return {}
        return parse_transfer(getattr(result, "stdout", "") or "")

    def teardown(self, interface: str) -> None:
        if self.interface_exists(interface):
            self._run(["ip", "link", "del", "dev", interface], check=False)
            logger.info("Tore down WireGuard interface %s", interface)
