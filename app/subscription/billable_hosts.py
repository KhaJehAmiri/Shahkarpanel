"""Keep subscription dial addresses on cores the panel can actually bill.

Hosts UI can list extra VLESS names that are not in ``nodes`` (no QueryStats,
no sing-box transfer). Clients such as Karing url-test pick the lowest-latency
endpoint; if that name is unmanaged the account stays offline with 0 traffic
while the app shows connected.
"""
from __future__ import annotations

import threading
import time
from typing import Iterable, Optional

_LOCK = threading.Lock()
_CACHE: tuple[float, frozenset[str]] = (0.0, frozenset())
_TTL_SEC = 15.0


def _norm(value: Optional[str]) -> str:
    text = (value or "").strip().lower()
    if not text:
        return ""
    if text.startswith("[") and "]" in text:
        return text[1 : text.index("]")].strip()
    if text.count(":") == 1 and not text.startswith("["):
        host, _, maybe_port = text.rpartition(":")
        if maybe_port.isdigit():
            return host.strip()
    return text


def connected_dial_names() -> frozenset[str]:
    """Hostnames/IPs of connected nodes (control address, provision host, SNI)."""
    global _CACHE
    now = time.monotonic()
    with _LOCK:
        if now - _CACHE[0] < _TTL_SEC:
            return _CACHE[1]

    names: set[str] = set()
    from app.db import GetDB
    from app.db.models import Node
    from app.subscription.node_eligibility import serviceable_nodes

    with GetDB() as db:
        # Same flap grace as the rest of subscription export: a node whose
        # channel blips must not silently strip its hosts from every profile.
        rows = serviceable_nodes(db.query(Node).all())
        for node in rows:
            for raw in (
                getattr(node, "address", None),
                getattr(node, "provision_host", None),
            ):
                n = _norm(raw)
                if n:
                    names.add(n)
            cfg = getattr(node, "singbox", None)
            sni = _norm(getattr(cfg, "sni", None) if cfg is not None else None)
            if sni:
                names.add(sni)

    frozen = frozenset(names)
    with _LOCK:
        _CACHE = (now, frozen)
    return frozen


def _address_list(host: dict) -> list[str]:
    raw = host.get("address") or []
    if isinstance(raw, str):
        return [raw]
    return [str(a) for a in raw]


def host_is_billable(host: dict, *, known: Optional[Iterable[str]] = None) -> bool:
    """True when this host can be attributed to a connected panel node.

    Template addresses (``{NODE_IP}``) fan out later. Explicit ``node_ids``
    keep CDN names that operators bound to a core. Bare extra hostnames with
    neither binding nor a matching node name are dropped.
    """
    from app.utils.node_ids import parse_node_ids

    if parse_node_ids(host.get("node_ids")):
        return True
    known_set = set(known) if known is not None else set(connected_dial_names())
    if not known_set:
        # Empty inventory: do not wipe every subscription (tests / fresh panel).
        return True
    addrs = _address_list(host)
    if not addrs:
        return True
    if any(("{NODE_IP}" in a) or ("{SERVER_IP}" in a) for a in addrs):
        return True
    return any(_norm(a) in known_set for a in addrs)
