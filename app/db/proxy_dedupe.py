"""Keep at most one ``Proxy`` row per ``(user_id, type)``.

The API / subscription models expose ``proxies`` as a dict keyed by type, but
the table had no unique constraint. Concurrent create/enable races could insert
two WireGuard rows with the same tunnel IP and different keys. Subscription
then exported one key while Finalmask baked the other — handshake failure.

Canonical row: the one whose ``public_key`` matches ``wg_peers`` (what the
node already has), otherwise the newest id. Extra rows are deleted.
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Sequence

from sqlalchemy.orm import Session

from app.db.models import Proxy, WgPeer, excluded_inbounds_association
from app.models.proxy import ProxyTypes


def _proxy_pubkey(proxy: Proxy) -> str:
    settings = proxy.settings or {}
    if not isinstance(settings, dict):
        return ""
    return str(settings.get("public_key") or "").strip()


def choose_canonical_proxy(
    proxies: Sequence[Proxy],
    *,
    wg_public_key: Optional[str] = None,
) -> Optional[Proxy]:
    rows = [p for p in proxies if p is not None]
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]
    key = (wg_public_key or "").strip()
    if key:
        for proxy in rows:
            if _proxy_pubkey(proxy) == key:
                return proxy
    return max(rows, key=lambda p: int(getattr(p, "id", 0) or 0))


def _wg_pubkey_for_user(db: Session, user_id: int) -> Optional[str]:
    row = db.query(WgPeer.public_key).filter(WgPeer.user_id == user_id).first()
    if row is None:
        return None
    return (row[0] or "").strip() or None


def _delete_proxy_rows(db: Session, rows: Iterable[Proxy]) -> int:
    victims = [p for p in rows if p is not None]
    ids = [p.id for p in victims if getattr(p, "id", None)]
    if ids:
        db.execute(
            excluded_inbounds_association.delete().where(
                excluded_inbounds_association.c.proxy_id.in_(ids)
            )
        )
    for proxy in victims:
        db.delete(proxy)
    return len(victims)


def get_user_proxy(
    db: Session,
    user_id: int,
    proxy_type: ProxyTypes,
    *,
    dedupe: bool = True,
) -> Optional[Proxy]:
    """Return the single proxy of ``proxy_type`` for ``user_id``.

    When duplicates exist, keep the canonical row and delete the rest.
    """
    rows: List[Proxy] = (
        db.query(Proxy)
        .filter(Proxy.user_id == user_id, Proxy.type == proxy_type)
        .order_by(Proxy.id.asc())
        .all()
    )
    if not rows:
        return None
    wg_key = None
    if proxy_type in (ProxyTypes.WireGuard, "WireGuard", "wireguard"):
        wg_key = _wg_pubkey_for_user(db, user_id)
    keep = choose_canonical_proxy(rows, wg_public_key=wg_key)
    if keep is None:
        return None
    extras = [p for p in rows if p.id != keep.id]
    if extras and dedupe:
        _delete_proxy_rows(db, extras)
        db.flush()
    return keep


def collapse_orm_proxies(proxies: Sequence[Proxy]) -> dict:
    """``{type: settings}`` with highest id winning (matches UserResponse)."""
    ordered = sorted(
        [p for p in (proxies or [])],
        key=lambda p: int(getattr(p, "id", 0) or 0),
    )
    out = {}
    for proxy in ordered:
        out[proxy.type] = proxy.settings
    return out
