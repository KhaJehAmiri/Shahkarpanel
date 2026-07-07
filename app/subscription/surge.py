"""Surge subscription exporter (MVP: VLESS/VMess/Trojan over TLS + WebSocket)."""
from __future__ import annotations

from typing import Any

# MVP scope: iOS clients with mature WS + TLS support only.
_SUPPORTED_PROTOCOLS = frozenset({"vless", "vmess", "trojan"})
_SUPPORTED_NETWORKS = frozenset({"ws"})


def _host_str(host: Any) -> str:
    if isinstance(host, list):
        return str(host[0]) if host else ""
    return str(host or "")


def _path_str(path: Any) -> str:
    text = str(path or "/").strip() or "/"
    return text if text.startswith("/") else f"/{text}"


def _truthy(val: Any) -> bool:
    return val in (True, "true", "1", 1, "yes")


def _tls_enabled(inbound: dict[str, Any]) -> bool:
    tls = inbound.get("tls")
    if _truthy(tls):
        return True
    return str(tls or "").lower() in ("tls", "reality")


def ios_mvp_supported(inbound: dict[str, Any]) -> bool:
    """Return True when inbound fits Surge/Loon/Quantumult X MVP (WS + limited protos)."""
    proto = str(inbound.get("protocol") or "").lower()
    if proto not in _SUPPORTED_PROTOCOLS:
        return False
    net = str(inbound.get("network") or "tcp").lower()
    if net not in _SUPPORTED_NETWORKS:
        return False
    # Reality / custom transports are out of MVP scope.
    if str(inbound.get("tls") or "").lower() == "reality":
        return False
    return True


def unique_proxy_remark(remark: str, existing: list[str]) -> str:
    base = (remark or "node").strip() or "node"
    if base not in existing:
        return base
    i = 2
    while f"{base} ({i})" in existing:
        i += 1
    return f"{base} ({i})"


def _ws_headers(host: str, sni: str) -> str:
    header_host = host or sni
    if not header_host:
        return ""
    return f"Host:{header_host}"


def build_surge_proxy_line(
    name: str,
    address: str,
    inbound: dict[str, Any],
    settings: dict[str, Any],
) -> str | None:
    if not ios_mvp_supported(inbound):
        return None

    proto = str(inbound.get("protocol") or "").lower()
    port = inbound.get("port") or 443
    tls = _tls_enabled(inbound)
    sni = str(inbound.get("sni") or "")
    fp = str(inbound.get("fp") or "chrome")
    path = _path_str(inbound.get("path"))
    ws_host = _host_str(inbound.get("host")) or sni or address
    ws_header = _ws_headers(ws_host, sni)

    safe_name = name.replace(",", "，")

    if proto == "vless":
        uuid = settings.get("id") or settings.get("uuid") or ""
        line = (
            f"{safe_name} = vless, {address}, {port}, username={uuid}, "
            f"encrypt-method=none, tfo=true"
        )
    elif proto == "vmess":
        uuid = settings.get("id") or settings.get("uuid") or ""
        line = (
            f"{safe_name} = vmess, {address}, {port}, username={uuid}, "
            f"encrypt-method=auto, vmess-aead=true, tfo=true"
        )
    elif proto == "trojan":
        password = settings.get("password") or ""
        line = f"{safe_name} = trojan, {address}, {port}, password={password}, tfo=true"
    else:
        return None

    if tls:
        line += ", tls=true"
        if sni:
            line += f", sni={sni}"
        line += f", client-fingerprint={fp}"
        if _truthy(inbound.get("ais")):
            line += ", skip-cert-verify=true"

    line += f', ws=true, ws-path="{path}"'
    if ws_header:
        line += f", ws-headers={ws_header}"

    return line


class SurgeConfiguration:
    """Minimal Surge [Proxy] section builder."""

    def __init__(self) -> None:
        self._proxies: list[str] = []
        self.proxy_remarks: list[str] = []

    def add(
        self,
        remark: str,
        address: str,
        inbound: dict[str, Any],
        settings: dict[str, Any],
    ) -> None:
        name = unique_proxy_remark(remark, self.proxy_remarks)
        line = build_surge_proxy_line(name, address, inbound, settings)
        if not line:
            return
        self.proxy_remarks.append(name)
        self._proxies.append(line)

    def render(self, reverse: bool = False) -> str:
        proxies = list(reversed(self._proxies)) if reverse else self._proxies
        body = "\n".join(proxies)
        return f"#!MANAGED-CONFIG interval=86400\n\n[Proxy]\n{body}\n"

    def __str__(self) -> str:
        return self.render()
