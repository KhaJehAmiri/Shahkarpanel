"""Host "inbound" buckets for the Hosts UI — including native (non-Xray) products.

Xray hosts are keyed by real inbound tags. WireGuard / sing-box have no Xray
inbound, so they use ``__native:*`` sentinel tags (same markers as user
templates) so operators can define subscription dial hosts the same way.
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Sequence

from app.models.user_template import NATIVE_TEMPLATE_MARKERS

# Host buckets operators can edit in Hosts UI (subset of native template markers).
NATIVE_HOST_TAGS: tuple[str, ...] = tuple(NATIVE_TEMPLATE_MARKERS.keys())


def is_native_host_tag(tag: str) -> bool:
    return (tag or "").strip() in NATIVE_TEMPLATE_MARKERS


def host_bucket_tags(xray_inbound_tags: Iterable[str]) -> List[str]:
    tags = list(xray_inbound_tags)
    for tag in NATIVE_HOST_TAGS:
        if tag not in tags:
            tags.append(tag)
    return tags


def native_host_label(tag: str) -> str:
    """Human label for UI (API still uses the sentinel tag)."""
    labels = {
        "__native:wireguard": "WireGuard",
        "__native:amneziawg": "AmneziaWG",
        "__native:hysteria2": "Hysteria2",
        "__native:tuic": "TUIC",
    }
    return labels.get(tag, tag)


def _is_non_routable_host(host: str) -> bool:
    h = (host or "").strip().lower().strip("[]")
    if not h or h in {"", "0.0.0.0", "::", "::1", "127.0.0.1", "localhost"}:
        return True
    if h.startswith("127."):
        return True
    return False


def _endpoint_host(raw: Optional[str]) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    if text.startswith("["):
        end = text.find("]")
        if end > 1:
            return text[1:end].strip()
    if text.count(":") == 1:
        return text.rsplit(":", 1)[0].strip()
    return text


def _node_public_ip(dbnode) -> str:
    """Best-effort public IP/hostname for ``{NODE_IP}`` expansion."""
    cfg = getattr(dbnode, "wireguard", None)
    candidates = [
        _endpoint_host(getattr(cfg, "endpoint", None) if cfg else None),
        _endpoint_host(getattr(cfg, "awg_endpoint", None) if cfg else None),
        (getattr(dbnode, "provision_host", None) or "").strip(),
        (getattr(dbnode, "address", None) or "").strip(),
    ]
    for candidate in candidates:
        if candidate and not _is_non_routable_host(candidate):
            return candidate
    for candidate in candidates:
        if candidate:
            return candidate
    return ""


def _expand_address(raw: str, *, panel_ip: str, node_ip: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    return (
        text.replace("{SERVER_IP}", panel_ip or "")
        .replace("{NODE_IP}", node_ip or "")
        .strip()
    )


def resolve_native_host_endpoints(
    tag: str,
    dbnode,
    *,
    default_port: int,
) -> List[tuple[str, int, str]]:
    """Return ``(host, port, remark)`` rows from Hosts for ``tag`` + ``dbnode``.

    Empty list means "no Hosts rows apply — use the product's built-in endpoint".
    """
    from app import xray
    from app.utils.node_ids import host_visible_on_node

    if not is_native_host_tag(tag):
        return []

    # Ensure native buckets are present in the in-memory cache.
    if tag not in xray.hosts:
        try:
            xray.hosts.update()
        except Exception:
            pass

    rows = list(xray.hosts.get(tag) or [])
    if not rows:
        return []

    try:
        from app.subscription.share import SERVER_IP as _PANEL_IP
    except Exception:
        try:
            from app.utils.system import get_public_ip

            _PANEL_IP = get_public_ip()
        except Exception:
            _PANEL_IP = ""

    node_id = getattr(dbnode, "id", None)
    node_ip = _node_public_ip(dbnode)
    panel_ip = str(_PANEL_IP or "")
    out: List[tuple[str, int, str]] = []

    for row in rows:
        if not host_visible_on_node(row.get("node_ids"), node_id):
            continue
        addresses: Sequence[str] = row.get("address") or []
        if isinstance(addresses, str):
            addresses = [a.strip() for a in addresses.split(",") if a.strip()]
        port = int(row.get("port") or default_port or 0)
        remark = str(row.get("remark") or "")
        for raw in addresses:
            host = _expand_address(str(raw), panel_ip=panel_ip, node_ip=node_ip)
            # Allow ``host:port`` inside address field.
            if host.count(":") == 1 and not host.startswith("["):
                h, p = host.rsplit(":", 1)
                try:
                    port = int(p)
                    host = h
                except ValueError:
                    pass
            host = _endpoint_host(host) or host
            if not host or _is_non_routable_host(host):
                continue
            if port <= 0:
                continue
            out.append((host, port, remark))
    return out


def wireguard_host_tag(variant: str) -> str:
    if variant == "awg":
        return "__native:amneziawg"
    return "__native:wireguard"


def singbox_dial_endpoints(
    dbnode,
    tag: str,
    *,
    default_host: str,
    default_port: int,
) -> List[tuple[str, int]]:
    """Hosts for Hysteria2/TUIC: Hosts UI rows, else the node's sni/address."""
    rows = resolve_native_host_endpoints(tag, dbnode, default_port=default_port)
    if rows:
        return [(h, p) for h, p, _remark in rows]
    host = (default_host or "").strip() or _node_public_ip(dbnode)
    if not host or default_port <= 0:
        return []
    return [(host, int(default_port))]
