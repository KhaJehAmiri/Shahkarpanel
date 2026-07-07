"""Concrete protocol backends.

Xray is fully wired (it is NexusPanel's engine today). The others are declared as
capability descriptors so the panel/UI can advertise the roadmap and so future
work can flip ``available`` once an engine is implemented behind the same
:class:`ProtocolBackend` contract.
"""
from .base import ProtocolBackend


class XrayBackend(ProtocolBackend):
    name = "xray"
    available = True
    protocols = ("vmess", "vless", "trojan", "shadowsocks")
    transports = ("tcp", "ws", "grpc", "http", "quic", "kcp")
    description = "Xray-core (default engine)."

    def health(self) -> dict:
        info = {"name": self.name, "available": self.available}
        try:
            from app import xray

            info["version"] = getattr(xray.core, "version", None)
            info["started"] = bool(getattr(xray.core, "started", False))
        except Exception:
            info["available"] = False
        return info


class SingBoxBackend(ProtocolBackend):
    name = "sing-box"
    available = True
    protocols = ("hysteria2", "tuic", "anytls")
    transports = ("quic", "tcp")
    description = "Sing-box engine (Hysteria2 / TUIC / AnyTLS on nodes)."


class Hysteria2Backend(ProtocolBackend):
    name = "hysteria2"
    available = True
    protocols = ("hysteria2",)
    transports = ("quic",)
    description = "Hysteria2 via sing-box."


class TuicBackend(ProtocolBackend):
    name = "tuic"
    available = True
    protocols = ("tuic",)
    transports = ("quic",)
    description = "TUIC v5 via sing-box."


class AnyTLSBackend(ProtocolBackend):
    name = "anytls"
    available = True
    protocols = ("anytls",)
    transports = ("tcp",)
    description = "AnyTLS via sing-box."
