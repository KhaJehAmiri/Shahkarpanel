"""Peer IP allocation for a WireGuard node's subnet.

Each WireGuard node owns a subnet (e.g. ``10.10.0.0/24``); the interface host
is reserved and every user peer gets a unique ``/32`` (or ``/128``) address
from the remaining hosts.

When the subnet was auto-widened from a non-aligned prefix, the historical
gateway may not be the widened net's canonical first host — pass it via
``reserved_hosts`` so peers never claim it.
"""
import ipaddress
from typing import Iterable, Optional


class WireGuardPeerIPAllocator:
    def __init__(
        self,
        subnet: str,
        used: Iterable[str] = (),
        reserve_first: bool = True,
        reserved_hosts: Iterable[str] = (),
    ):
        self.network = ipaddress.ip_network(subnet, strict=False)
        self.reserve_first = reserve_first
        self.used = set()
        for entry in used:
            addr = self._coerce(entry)
            if addr is not None:
                self.used.add(addr)

        explicit = []
        for entry in reserved_hosts:
            addr = self._coerce(entry)
            if addr is not None:
                explicit.append(addr)
                self.used.add(addr)

        # Legacy / aligned: reserve canonical first host when caller did not
        # supply an explicit interface host list.
        if reserve_first and not explicit:
            server = next(self.network.hosts(), None)
            if server is not None:
                self.used.add(server)

    @staticmethod
    def _coerce(entry) -> Optional[ipaddress._BaseAddress]:
        if entry in (None, ""):
            return None
        try:
            return ipaddress.ip_address(str(entry).split("/")[0])
        except ValueError:
            return None

    @property
    def _prefix(self) -> int:
        return 32 if self.network.version == 4 else 128

    def allocate(self) -> Optional[str]:
        """Return the next free address as ``"<ip>/<prefix>"`` or ``None`` when
        the subnet is exhausted."""
        for host in self.network.hosts():
            if host in self.used:
                continue
            self.used.add(host)
            return f"{host}/{self._prefix}"
        return None

    def reserve(self, address: str) -> None:
        addr = self._coerce(address)
        if addr is not None:
            self.used.add(addr)
