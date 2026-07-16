"""Iran agent-image mirror: detect IR nodes and pick the download URL."""
from __future__ import annotations

import logging
import socket
from typing import Optional
from urllib.parse import urlparse

from app.utils.panel_region import node_region_is_iran

logger = logging.getLogger("uvicorn.error")


def _host_looks_like_ip(host: str) -> bool:
    host = (host or "").strip()
    if not host:
        return False
    # Strip brackets for IPv6 literals.
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    try:
        socket.inet_pton(socket.AF_INET, host)
        return True
    except OSError:
        pass
    try:
        socket.inet_pton(socket.AF_INET6, host)
        return True
    except OSError:
        return False


def _resolve_ipv4(host: str) -> Optional[str]:
    host = (host or "").strip()
    if not host:
        return None
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if _host_looks_like_ip(host):
        # Only IPv4 GeoIP path for now.
        try:
            socket.inet_pton(socket.AF_INET, host)
            return host
        except OSError:
            return None
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)
    except socket.gaierror:
        return None
    for info in infos:
        addr = info[4][0]
        if addr:
            return addr
    return None


def _geoip_is_iran(ip: str) -> bool:
    from app.utils.panel_region import _country_code

    cc = _country_code(ip)
    return cc == "IR"


def node_is_iran(*, region: Optional[str] = None, host: Optional[str] = None) -> bool:
    """True when the node should use the domestic Iran agent-image mirror."""
    if node_region_is_iran(region):
        return True
    ip = _resolve_ipv4(host or "")
    if not ip:
        return False
    try:
        return _geoip_is_iran(ip)
    except Exception:
        logger.debug("Iran GeoIP check failed for %s", ip, exc_info=True)
        return False


def mirror_url_configured() -> Optional[str]:
    from config import NODE_AGENT_MIRROR_URL

    url = (NODE_AGENT_MIRROR_URL or "").strip()
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        logger.warning("NODE_AGENT_MIRROR_URL is not a valid http(s) URL: %s", url)
        return None
    return url


def agent_image_fetch_url(
    *,
    panel_agent_url: str,
    region: Optional[str] = None,
    host: Optional[str] = None,
) -> tuple[str, bool]:
    """Return ``(url, used_mirror)`` for the node install script's curl|load step."""
    mirror = mirror_url_configured()
    if mirror and node_is_iran(region=region, host=host):
        return mirror, True
    return panel_agent_url, False
