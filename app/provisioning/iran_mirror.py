"""Iran agent-image mirror: auto-detect IR nodes by server IP and pick download URL."""
from __future__ import annotations

import logging
import socket
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger("uvicorn.error")


def _host_looks_like_ip(host: str) -> bool:
    host = (host or "").strip()
    if not host:
        return False
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
    """Resolve provision host to an IPv4 address for GeoIP (ignore UI region)."""
    host = (host or "").strip()
    if not host:
        return None
    # Drop accidental port suffixes (1.2.3.4:22) — not for hostnames with colons (IPv6).
    if host.count(":") == 1 and not host.startswith("["):
        host = host.split(":", 1)[0]
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if _host_looks_like_ip(host):
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


def node_host_is_iran(host: Optional[str] = None) -> bool:
    """True when the provision SSH host's public IP geolocates to Iran.

    UI region is intentionally ignored — operators should not have to pick
    Iran for the domestic agent-image mirror to kick in.
    """
    ip = _resolve_ipv4(host or "")
    if not ip:
        return False
    try:
        hit = _geoip_is_iran(ip)
        if hit:
            logger.info("Provision host %s (%s) detected as Iran — using agent mirror", host, ip)
        return hit
    except Exception:
        logger.debug("Iran GeoIP check failed for %s", ip, exc_info=True)
        return False


# Back-compat alias (region arg ignored).
def node_is_iran(*, region: Optional[str] = None, host: Optional[str] = None) -> bool:
    _ = region
    return node_host_is_iran(host)


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
    """Return ``(url, used_mirror)`` based on GeoIP of ``host`` only."""
    _ = region
    mirror = mirror_url_configured()
    if mirror and node_host_is_iran(host):
        return mirror, True
    return panel_agent_url, False
