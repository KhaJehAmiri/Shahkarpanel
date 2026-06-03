"""Protocol backend abstraction.

A *backend* is a proxy engine (Xray today; Sing-box / Hysteria2 / TUIC in
future) capable of serving one or more protocols over a set of transports.
This abstraction lets the rest of the panel reason about capabilities without
hard-coding Xray, enabling a gradual multi-engine refactor.
"""
from typing import Tuple


class ProtocolBackend:
    name: str = "base"
    # Whether the backend is wired up and usable in this build.
    available: bool = False
    # Protocols the backend can serve (vmess, vless, trojan, shadowsocks, ...).
    protocols: Tuple[str, ...] = ()
    # Network transports it supports (tcp, ws, grpc, quic, ...).
    transports: Tuple[str, ...] = ()
    description: str = ""

    def supports(self, protocol: str) -> bool:
        return protocol in self.protocols

    def health(self) -> dict:
        """Backend health/version info. Overridden by concrete backends."""
        return {"name": self.name, "available": self.available}

    def capability(self) -> dict:
        return {
            "name": self.name,
            "available": self.available,
            "protocols": list(self.protocols),
            "transports": list(self.transports),
            "description": self.description,
        }
