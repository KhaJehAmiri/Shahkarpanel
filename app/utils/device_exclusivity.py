"""Live cross-protocol exclusivity for ``device_limit == 1``.

When a user is capped to one device, only one protocol family may stay online:
``wireguard``, ``xray`` (VLESS/VMess/Trojan/SS/…), or ``singbox`` (Hy2/TUIC/AnyTLS).
The winner is sticky until it goes quiet for ``ONLINE_WINDOW_MINUTES``; losers are
held out of live serving without changing ``User.status``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from sqlalchemy.orm import Session

from app.db.models import User

logger = logging.getLogger("shahkar-device-exclusivity")

PROTO_WG = "wireguard"
PROTO_XRAY = "xray"
PROTO_SINGBOX = "singbox"
ALL_PROTOS = (PROTO_WG, PROTO_XRAY, PROTO_SINGBOX)

# Map collector labels from record_usages protocol_breakdown → family.
_LABEL_TO_FAMILY = {
    "wireguard": PROTO_WG,
    "xray": PROTO_XRAY,
    "singbox": PROTO_SINGBOX,
    "hysteria2": PROTO_SINGBOX,
    "tuic": PROTO_SINGBOX,
    "anytls": PROTO_SINGBOX,
}


def normalize_hold(raw: Any) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None
    winner = raw.get("winner")
    held = raw.get("held")
    if winner not in ALL_PROTOS or not isinstance(held, list):
        return None
    held_clean = [p for p in held if p in ALL_PROTOS and p != winner]
    return {
        "winner": winner,
        "held": held_clean,
        "updated_at": str(raw.get("updated_at") or ""),
    }


def get_hold(dbuser: User) -> Optional[dict]:
    return normalize_hold(getattr(dbuser, "device_conn_hold", None))


def is_protocol_held(dbuser: User, protocol: str) -> bool:
    hold = get_hold(dbuser)
    if not hold:
        return False
    return protocol in (hold.get("held") or [])


def is_xray_proxy_held(dbuser: User, proxy_type: str) -> bool:
    """Whether an Xray config proxy type should be omitted for this user."""
    pt = (proxy_type or "").lower()
    if pt in ("wireguard", "amneziawg"):
        return is_protocol_held(dbuser, PROTO_WG)
    return is_protocol_held(dbuser, PROTO_XRAY)


def bytes_by_family(
    protocol_breakdown: Sequence[dict],
    *,
    uids: Optional[Set[int]] = None,
) -> Dict[int, Dict[str, int]]:
    """Aggregate this-tick bytes per user per protocol family."""
    out: Dict[int, Dict[str, int]] = {}
    for entry in protocol_breakdown or []:
        family = _LABEL_TO_FAMILY.get(str(entry.get("protocol") or "").lower())
        if not family:
            continue
        coef = float(entry.get("coefficient") or 1)
        for param in entry.get("params") or []:
            try:
                uid = int(param["uid"])
            except (KeyError, TypeError, ValueError):
                continue
            if uids is not None and uid not in uids:
                continue
            value = int(param.get("value") or 0)
            if value <= 0:
                continue
            bucket = out.setdefault(uid, {})
            bucket[family] = bucket.get(family, 0) + int(value * coef)
    return out


def pick_winner(
    live_bytes: Dict[str, int],
    *,
    sticky: Optional[str] = None,
) -> Optional[str]:
    """Choose the exclusive winner among families with traffic this tick."""
    live = {k: v for k, v in live_bytes.items() if v > 0 and k in ALL_PROTOS}
    if not live:
        return None
    if sticky in live:
        return sticky
    # Prefer highest bytes; tie-break: wireguard > xray > singbox.
    priority = {PROTO_WG: 0, PROTO_XRAY: 1, PROTO_SINGBOX: 2}
    return min(live.keys(), key=lambda p: (-live[p], priority.get(p, 9)))


def desired_hold_for_winner(winner: str) -> dict:
    held = [p for p in ALL_PROTOS if p != winner]
    return {
        "winner": winner,
        "held": held,
        "updated_at": datetime.utcnow().isoformat(),
    }


def _online_window() -> timedelta:
    from config import ONLINE_WINDOW_MINUTES

    return timedelta(minutes=max(1, int(ONLINE_WINDOW_MINUTES or 1)))


def winner_still_online(dbuser: User, *, now: Optional[datetime] = None) -> bool:
    """True when the account still looks live within the dashboard online window."""
    from app.utils.device_limit import account_is_online

    return account_is_online(dbuser, now=now)


def decide_hold(
    dbuser: User,
    live_bytes: Dict[str, int],
    *,
    now: Optional[datetime] = None,
) -> Optional[dict]:
    """Compute the next ``device_conn_hold`` for a ``device_limit == 1`` user.

    Returns ``None`` when no hold should be active (clear / unlimited / quiet).
    """
    limit = getattr(dbuser, "device_limit", None)
    if not limit or int(limit) != 1:
        return None

    current = get_hold(dbuser)
    sticky = current["winner"] if current else None
    live = {k: v for k, v in (live_bytes or {}).items() if v > 0}

    if live:
        # Multiple families this tick, or first acquisition.
        winner = pick_winner(live, sticky=sticky)
        if winner is None:
            return None
        if len(live) == 1 and winner == sticky and current:
            # Refresh timestamp only.
            out = dict(current)
            out["updated_at"] = datetime.utcnow().isoformat()
            return out
        return desired_hold_for_winner(winner)

    # No traffic this tick: keep sticky hold while account still online.
    if current and winner_still_online(dbuser, now=now):
        return current
    return None


def _mark_finalmask_dirty_for_users(db: Session, user_ids: Iterable[int]) -> None:
    try:
        from app.db.models import Proxy
        from app.models.proxy import ProxyTypes
        from app.wireguard.finalmask_reload import mark_finalmask_slots_dirty
        from app.wireguard.finalmask_shard import user_finalmask_slot

        slots = set()
        uids = [int(u) for u in user_ids]
        if not uids:
            return
        for proxy in (
            db.query(Proxy)
            .filter(Proxy.user_id.in_(uids), Proxy.type == ProxyTypes.WireGuard)
            .all()
        ):
            slot = user_finalmask_slot(dict(proxy.settings or {}))
            if slot is not None:
                slots.add(int(slot))
        if slots:
            mark_finalmask_slots_dirty(slots)
    except Exception:
        logger.debug("Finalmask dirty-slot mark skipped", exc_info=True)


def apply_protocol_holds(
    users: Sequence[User],
    *,
    previous: Dict[int, Optional[dict]],
) -> None:
    """Apply hold transitions (hot disconnect / peer toggle / sing-box sync).

    Must run **after** ``device_conn_hold`` is committed. ``previous`` maps
    user_id → prior hold (or None).
    """
    from types import SimpleNamespace

    xray_hold: List[Any] = []
    xray_release: List[int] = []
    wg_disable: List[int] = []
    wg_enable: List[int] = []
    singbox_touch = False

    for dbuser in users:
        uid = int(dbuser.id)
        new = get_hold(dbuser)
        old = normalize_hold(previous.get(uid))
        old_held = set((old or {}).get("held") or [])
        new_held = set((new or {}).get("held") or [])

        if PROTO_XRAY in new_held and PROTO_XRAY not in old_held:
            xray_hold.append(SimpleNamespace(id=dbuser.id, username=dbuser.username))
        if PROTO_XRAY not in new_held and PROTO_XRAY in old_held:
            xray_release.append(uid)

        if PROTO_WG in new_held and PROTO_WG not in old_held:
            wg_disable.append(uid)
        if PROTO_WG not in new_held and PROTO_WG in old_held:
            wg_enable.append(uid)

        if (PROTO_SINGBOX in new_held) != (PROTO_SINGBOX in old_held):
            singbox_touch = True

    if xray_hold:
        try:
            from app.xray.serving import hot_disconnect_users

            hot_disconnect_users(xray_hold)
        except Exception:
            logger.debug("exclusivity xray hold disconnect failed", exc_info=True)
        try:
            from app.xray.operations import hot_disconnect_users_on_nodes

            hot_disconnect_users_on_nodes(xray_hold)
        except Exception:
            logger.debug("exclusivity xray node hold failed", exc_info=True)

    if xray_release:
        try:
            from app.db import GetDB, crud
            from app.xray import operations as xops

            with GetDB() as db:
                for uid in xray_release:
                    dbuser = crud.get_user_by_id(db, uid)
                    if dbuser is None:
                        continue
                    if is_protocol_held(dbuser, PROTO_XRAY):
                        continue
                    try:
                        xops.update_user(dbuser)
                    except Exception:
                        logger.debug(
                            "exclusivity xray restore failed for %s", uid, exc_info=True
                        )
        except Exception:
            logger.debug("exclusivity xray restore batch failed", exc_info=True)

    if wg_disable or wg_enable:
        try:
            from app.db import GetDB
            from app.wireguard.peer_cache import peer_cache
            from app.wireguard.wg_manager import toggle_peer

            with GetDB() as db:
                for uid in wg_disable:
                    try:
                        toggle_peer(db, uid, active=False)
                    except Exception:
                        logger.debug("exclusivity wg hold failed %s", uid, exc_info=True)
                for uid in wg_enable:
                    try:
                        toggle_peer(db, uid, active=True)
                    except Exception:
                        logger.debug(
                            "exclusivity wg restore failed %s", uid, exc_info=True
                        )
                _mark_finalmask_dirty_for_users(db, wg_disable + wg_enable)
            peer_cache.invalidate()
        except Exception:
            logger.debug("exclusivity wg toggle batch failed", exc_info=True)
        try:
            from app.wireguard.finalmask_reload import flush_finalmask_xray_reload
            from app.wireguard.operations import sync_user_change as wg_sync

            flush_finalmask_xray_reload(urgent=True)
            wg_sync(immediate=False)
        except Exception:
            logger.debug("exclusivity wg sync failed", exc_info=True)

    if singbox_touch:
        try:
            from app.singbox.operations import sync_user_change

            sync_user_change()
        except Exception:
            logger.debug("exclusivity singbox sync failed", exc_info=True)


def kick_excess_xray_ips(dbuser: User) -> None:
    """Best-effort: reset Xray sessions when live online IP count exceeds limit."""
    if is_protocol_held(dbuser, PROTO_XRAY):
        return
    limit = getattr(dbuser, "device_limit", None)
    try:
        cap = int(limit) if limit is not None and int(limit) > 0 else 1
    except (TypeError, ValueError):
        cap = 1
    try:
        from app.utils.device_limit import _xray_online_device_count

        n = _xray_online_device_count(dbuser)
    except Exception:
        return
    if n is None or n <= cap:
        return
    try:
        from app.xray.operations import update_user
        from app.xray.serving import hot_disconnect_users

        hot_disconnect_users([dbuser])
        update_user(dbuser)
    except Exception:
        logger.debug("exclusivity excess-ip kick failed for %s", dbuser.id, exc_info=True)


def enforce_device_exclusivity(
    protocol_breakdown: Sequence[dict],
    candidate_uids: Optional[Iterable[int]] = None,
) -> int:
    """Evaluate and apply holds for ``device_limit == 1`` users.

    Returns the number of users whose hold JSON changed.
    Safe to call outside a DB transaction (opens its own short sessions).
    """
    from app.db import GetDB

    by_family = bytes_by_family(
        protocol_breakdown,
        uids=set(int(u) for u in candidate_uids) if candidate_uids is not None else None,
    )

    with GetDB() as db:
        held_ids = {
            row[0]
            for row in db.query(User.id)
            .filter(User.device_limit == 1, User.device_conn_hold.isnot(None))
            .all()
        }
        target_ids = set(by_family.keys()) | held_ids
        if candidate_uids is not None:
            target_ids |= {int(u) for u in candidate_uids}
        if not target_ids:
            return 0
        targets = (
            db.query(User)
            .filter(User.device_limit == 1, User.id.in_(target_ids))
            .all()
        )
        if not targets:
            return 0

        previous: Dict[int, Optional[dict]] = {}
        changed: List[User] = []
        now = datetime.utcnow()
        dirty = False

        for dbuser in targets:
            uid = int(dbuser.id)
            previous[uid] = get_hold(dbuser)
            live = by_family.get(uid, {})
            next_hold = decide_hold(dbuser, live, now=now)
            old_norm = previous[uid]
            new_norm = normalize_hold(next_hold) if next_hold else None
            old_key = (
                (old_norm or {}).get("winner"),
                tuple(sorted((old_norm or {}).get("held") or [])),
            )
            new_key = (
                (new_norm or {}).get("winner"),
                tuple(sorted((new_norm or {}).get("held") or [])),
            )
            if old_key == new_key:
                if new_norm and live:
                    dbuser.device_conn_hold = desired_hold_for_winner(new_norm["winner"])
                    dirty = True
                continue
            dbuser.device_conn_hold = new_norm
            changed.append(dbuser)
            dirty = True

        if dirty:
            db.commit()
            for u in changed:
                db.refresh(u)

        changed_ids = {int(u.id) for u in changed}
        kick_users = [
            u
            for u in targets
            if not is_protocol_held(u, PROTO_XRAY)
            and (
                by_family.get(int(u.id), {}).get(PROTO_XRAY, 0) > 0
                or (get_hold(u) or {}).get("winner") == PROTO_XRAY
            )
        ]

    if changed:
        apply_protocol_holds(changed, previous=previous)

    for dbuser in kick_users:
        if int(dbuser.id) in changed_ids and is_protocol_held(dbuser, PROTO_XRAY):
            continue
        kick_excess_xray_ips(dbuser)

    return len(changed)
