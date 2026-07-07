"""Quantumult X subscription exporter (MVP: vmess/vless/trojan share links, WS-only)."""
from __future__ import annotations

import base64
import json
from typing import Any
from urllib.parse import quote, urlencode

from app.subscription.surge import _host_str, _path_str, _tls_enabled, ios_mvp_supported, unique_proxy_remark


def _fragment_name(name: str) -> str:
    return quote(name, safe="")


def build_quantumult_line(
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
    path = _path_str(inbound.get("path"))
    ws_host = _host_str(inbound.get("host")) or sni or address

    if proto == "vmess":
        uuid = settings.get("id") or settings.get("uuid") or ""
        obj = {
            "v": "2",
            "ps": name,
            "add": address,
            "port": str(port),
            "id": uuid,
            "aid": "0",
            "net": "ws",
            "type": "none",
            "host": ws_host,
            "path": path,
            "tls": "tls" if tls else "",
            "sni": sni,
        }
        payload = base64.b64encode(json.dumps(obj, separators=(",", ":")).encode()).decode()
        return f"vmess://{payload}"

    if proto == "trojan":
        password = settings.get("password") or ""
        params: dict[str, str] = {
            "allowInsecure": "1" if inbound.get("ais") else "0",
            "type": "ws",
            "path": path,
            "host": ws_host,
        }
        if sni:
            params["peer"] = sni
            params["sni"] = sni
        query = urlencode(params)
        return f"trojan://{password}@{address}:{port}?{query}#{_fragment_name(name)}"

    if proto == "vless":
        uuid = settings.get("id") or settings.get("uuid") or ""
        params = {
            "encryption": "none",
            "security": "tls" if tls else "none",
            "type": "ws",
            "path": path,
            "host": ws_host,
        }
        if sni:
            params["sni"] = sni
        query = urlencode(params)
        return f"vless://{uuid}@{address}:{port}?{query}#{_fragment_name(name)}"

    return None


class QuantumultConfiguration:
    """Minimal Quantumult X [SERVER] section builder."""

    def __init__(self) -> None:
        self._lines: list[str] = []
        self.proxy_remarks: list[str] = []

    def add(
        self,
        remark: str,
        address: str,
        inbound: dict[str, Any],
        settings: dict[str, Any],
    ) -> None:
        name = unique_proxy_remark(remark, self.proxy_remarks)
        line = build_quantumult_line(name, address, inbound, settings)
        if not line:
            return
        self.proxy_remarks.append(name)
        self._lines.append(line)

    def render(self, reverse: bool = False) -> str:
        if not self._lines:
            return ""
        lines = list(reversed(self._lines)) if reverse else self._lines
        return "\n".join(lines) + "\n"
