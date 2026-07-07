"""Loon subscription exporter (MVP: reuses Surge WS proxy lines)."""
from __future__ import annotations

from typing import Any

from app.subscription.surge import build_surge_proxy_line, unique_proxy_remark


class LoonConfiguration:
    """Minimal Loon [Proxy] section builder."""

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
        if not self._proxies:
            return ""
        proxies = list(reversed(self._proxies)) if reverse else self._proxies
        return "[Proxy]\n" + "\n".join(proxies) + "\n"
