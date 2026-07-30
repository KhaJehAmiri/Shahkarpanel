"""Per-user concurrent device limiting for subscription access."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.db.models import User

# IPs/fingerprints not seen within this window don't count toward the device limit.
_ACTIVE_WINDOW = timedelta(hours=24)
# Subscribe UI "recent devices" window for fingerprint fallback.
_ONLINE_DISPLAY_WINDOW = timedelta(hours=2)


def _parse_ips(raw: Optional[str]) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _entry_seen(value: Any) -> Optional[str]:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        seen = value.get("seen")
        return str(seen) if seen else None
    return None


def _prune(ips: dict[str, Any], now: datetime, window: timedelta = _ACTIVE_WINDOW) -> dict[str, Any]:
    cutoff = now - window
    out: dict[str, Any] = {}
    for key, value in ips.items():
        seen_raw = _entry_seen(value)
        if not seen_raw:
            continue
        try:
            ts = datetime.fromisoformat(str(seen_raw))
            if ts.tzinfo is not None:
                ts = ts.replace(tzinfo=None)
        except ValueError:
            continue
        if ts >= cutoff:
            out[key] = value
    return out


def _infrastructure_ips() -> frozenset[str]:
    """Panel/node addresses must not consume user device slots."""
    now = time.monotonic()
    cached = getattr(_infrastructure_ips, "_cache", None)
    if cached and (now - cached[0]) < 60.0:
        return cached[1]

    from app.utils.system import get_public_ip, get_public_ipv6

    ips = {"127.0.0.1", "::1", "unknown"}
    panel_ip = get_public_ip()
    if panel_ip:
        ips.add(panel_ip)
    panel_v6 = get_public_ipv6()
    if panel_v6:
        ips.add(panel_v6)
    try:
        from app import xray

        for node in xray.nodes.values():
            addr = getattr(node, "address", None)
            if addr:
                ips.add(str(addr))
    except Exception:
        pass
    try:
        from app.db import GetDB
        from app.db.models import Node

        with GetDB() as db:
            for row in db.query(Node.address).all():
                if row[0]:
                    ips.add(str(row[0]))
    except Exception:
        pass
    result = frozenset(ips)
    _infrastructure_ips._cache = (now, result)
    return result


def _is_infrastructure_ip(client_ip: str) -> bool:
    return not client_ip or client_ip in _infrastructure_ips()


def _client_device_entries(ips: dict[str, Any]) -> dict[str, Any]:
    """Drop bare infrastructure IP keys; keep fingerprint keys always."""
    infra = _infrastructure_ips()
    out: dict[str, Any] = {}
    for key, value in ips.items():
        if key.startswith(("fp:", "hw:")):
            out[key] = value
            continue
        if key not in infra:
            out[key] = value
    return out


def device_fingerprint(client_ip: str, user_agent: str = "", hwid: str = "") -> str:
    """Stable device id: prefer client HWID, else hash(IP + User-Agent)."""
    hw = (hwid or "").strip()
    if hw:
        return "hw:" + hashlib.sha256(hw.encode("utf-8", errors="ignore")).hexdigest()[:20]
    ua = (user_agent or "").strip()
    raw = f"{client_ip}|{ua}".encode("utf-8", errors="ignore")
    return "fp:" + hashlib.sha256(raw).hexdigest()[:20]


def count_active_devices(dbuser: User) -> int:
    """How many distinct devices are currently counted toward the device limit."""
    now = datetime.utcnow()
    ips = _client_device_entries(_prune(_parse_ips(getattr(dbuser, "device_ips", None)), now))
    return len(ips)


def account_is_online(dbuser: User, now: Optional[datetime] = None) -> bool:
    """Same live window as the admin dashboard online counter."""
    from config import ONLINE_WINDOW_MINUTES

    online_at = getattr(dbuser, "online_at", None)
    if online_at is None:
        return False
    seen = online_at.replace(tzinfo=None) if online_at.tzinfo is not None else online_at
    now = now or datetime.utcnow()
    return now - seen <= timedelta(minutes=ONLINE_WINDOW_MINUTES)


def _xray_online_device_count(dbuser: User) -> Optional[int]:
    """Live concurrent IPs from Xray ``statsUserOnline`` (panel + nodes).

    Returns ``None`` when the core cannot be queried (stats disabled / API down).
    """
    email = f"{dbuser.id}.{dbuser.username}"
    total = 0
    got_any = False
    try:
        from app import xray

        apis = []
        if getattr(xray, "api", None) is not None:
            apis.append(xray.api)
        for node in (getattr(xray, "nodes", None) or {}).values():
            api = getattr(node, "api", None)
            if api is not None:
                apis.append(api)
        for api in apis:
            try:
                n = int(api.get_user_online_count(email, timeout=2) or 0)
            except Exception:
                continue
            got_any = True
            if n > 0:
                total += n
    except Exception:
        return None
    if not got_any:
        return None
    return total


def count_online_devices(dbuser: User, *, live: bool = True) -> int:
    """Devices currently connected for the subscribe overview.

    Prefer live Xray online-IP counters (true concurrent VPN clients). Fall back
    to distinct subscription fingerprints (HWID / IP+UA) seen recently. When the
    account is online via traffic but nothing was tracked, return at least ``1``.

    ``live=False`` skips Xray RPC (portal boot / list endpoints) — local data only.
    """
    now = datetime.utcnow()
    online = account_is_online(dbuser, now)
    if not online:
        return 0

    if live:
        live_n = _xray_online_device_count(dbuser)
        if live_n is not None and live_n > 0:
            return live_n

    entries = _client_device_entries(
        _prune(
            _parse_ips(getattr(dbuser, "device_ips", None)),
            now,
            window=_ONLINE_DISPLAY_WINDOW,
        )
    )
    n = len(entries)
    return max(n, 1)


def record_and_check_device_limit(
    db: Session,
    dbuser: User,
    client_ip: str,
    user_agent: str = "",
    hwid: str = "",
) -> None:
    """Track a device fingerprint and raise if the user exceeds ``device_limit``.

    Keys are ``hw:…`` / ``fp:…`` (not bare IPs) so two phones behind the same NAT
    count as two devices when their User-Agent or HWID differs. ``device_limit``
    of ``None`` or ``0`` means unlimited — tracking still runs.
    """
    from fastapi import HTTPException

    if _is_infrastructure_ip(client_ip):
        return

    now = datetime.utcnow()
    key = device_fingerprint(client_ip, user_agent=user_agent, hwid=hwid)
    ips = _client_device_entries(_prune(_parse_ips(getattr(dbuser, "device_ips", None)), now))

    entry = {
        "seen": now.isoformat(),
        "ip": client_ip,
        "ua": (user_agent or "")[:180],
    }

    if key in ips:
        ips[key] = entry
        dbuser.device_ips = json.dumps(ips)
        if db is not None:
            db.commit()
        return

    limit = getattr(dbuser, "device_limit", None)
    if limit and limit > 0 and len(ips) >= int(limit):
        raise HTTPException(
            status_code=403,
            detail=f"Device limit reached ({limit} concurrent devices)",
        )

    ips[key] = entry
    dbuser.device_ips = json.dumps(ips)
    if db is not None:
        db.commit()
