"""Build ProxyHost rows from migrated 3x-ui inbound stream_settings."""
from __future__ import annotations

import json
from typing import Any

from app.models.proxy import ProxyHost, ProxyHostFingerprint, ProxyHostSecurity


def _parse_stream(inbound: dict) -> dict[str, Any]:
    stream = inbound.get("streamSettings") or inbound.get("stream") or {}
    if isinstance(stream, str):
        try:
            stream = json.loads(stream)
        except json.JSONDecodeError:
            stream = {}
    return stream if isinstance(stream, dict) else {}


def _first_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        for item in value:
            text = str(item or "").strip()
            if text:
                return text
        return None
    text = str(value).strip()
    return text or None


def _network_path(stream: dict) -> str | None:
    network = str(stream.get("network") or "tcp").lower()
    if network == "ws":
        return _first_str((stream.get("wsSettings") or {}).get("path"))
    if network in ("xhttp", "splithttp"):
        return _first_str((stream.get("xhttpSettings") or stream.get("splithttpSettings") or {}).get("path"))
    if network == "grpc":
        return _first_str((stream.get("grpcSettings") or {}).get("serviceName"))
    if network == "http":
        return _first_str((stream.get("httpSettings") or {}).get("path"))
    return None


def _network_host_header(stream: dict) -> str | None:
    network = str(stream.get("network") or "tcp").lower()
    if network == "ws":
        return _first_str((stream.get("wsSettings") or {}).get("headers", {}).get("Host"))
    if network in ("xhttp", "splithttp"):
        return _first_str((stream.get("xhttpSettings") or stream.get("splithttpSettings") or {}).get("host"))
    if network == "http":
        return _first_str((stream.get("httpSettings") or {}).get("host"))
    return None


def _resolve_sni(stream: dict) -> str | None:
    security = str(stream.get("security") or "none").lower()
    if security == "reality":
        rs = stream.get("realitySettings") or {}
        return _first_str(rs.get("serverNames"))
    if security == "tls":
        tls = stream.get("tlsSettings") or {}
        return _first_str(tls.get("serverName"))
    return None


def _resolve_fingerprint(stream: dict) -> ProxyHostFingerprint:
    security = str(stream.get("security") or "none").lower()
    fp = ""
    if security == "reality":
        rs = stream.get("realitySettings") or {}
        fp = str(rs.get("fingerprint") or rs.get("fp") or "").strip()
    if not fp and security == "tls":
        tls = stream.get("tlsSettings") or {}
        fp = str(tls.get("fingerprint") or tls.get("fp") or "").strip()
    if not fp:
        return ProxyHostFingerprint.none
    try:
        return ProxyHostFingerprint(fp)
    except ValueError:
        return ProxyHostFingerprint.none


def _resolve_security(stream: dict) -> ProxyHostSecurity:
    security = str(stream.get("security") or "none").lower()
    if security == "reality":
        return ProxyHostSecurity.reality
    if security == "tls":
        return ProxyHostSecurity.tls
    if security == "none":
        return ProxyHostSecurity.none
    return ProxyHostSecurity.inbound_default


def build_migration_host(
    *,
    panel_slug: str,
    inbound_tag: str,
    inbound: dict,
    subscription_host: str | None,
) -> ProxyHost | None:
    """Return a ProxyHost for subscription export parity with legacy 3x-ui."""
    address = (subscription_host or "").strip().lower()
    if not address:
        return None

    stream = _parse_stream(inbound)
    remark = f"{panel_slug} {inbound.get('remark') or inbound_tag}".strip()
    try:
        port = int(inbound.get("port") or 0)
    except (TypeError, ValueError):
        port = 0

    return ProxyHost(
        remark=remark[:256],
        address=address,
        port=port if port > 0 else None,
        path=_network_path(stream),
        sni=_resolve_sni(stream),
        host=_network_host_header(stream),
        security=_resolve_security(stream),
        fingerprint=_resolve_fingerprint(stream),
    )
