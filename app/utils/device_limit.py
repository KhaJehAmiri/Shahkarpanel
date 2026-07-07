"""Per-user concurrent device (IP) limiting for subscription access."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import User

# IPs not seen within this window don't count toward the device limit.
_ACTIVE_WINDOW = timedelta(hours=24)


def _parse_ips(raw: Optional[str]) -> dict[str, str]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _prune(ips: dict[str, str], now: datetime) -> dict[str, str]:
    cutoff = now - _ACTIVE_WINDOW
    out: dict[str, str] = {}
    for ip, seen in ips.items():
        try:
            ts = datetime.fromisoformat(str(seen))
        except ValueError:
            continue
        if ts >= cutoff:
            out[ip] = seen
    return out


def _infrastructure_ips() -> frozenset[str]:
    """Panel/node addresses must not consume user device slots."""
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
    return frozenset(ips)


def _is_infrastructure_ip(client_ip: str) -> bool:
    return not client_ip or client_ip in _infrastructure_ips()


def _client_device_ips(ips: dict[str, str]) -> dict[str, str]:
    infra = _infrastructure_ips()
    return {ip: seen for ip, seen in ips.items() if ip not in infra}


def record_and_check_device_limit(db: Session, dbuser: User, client_ip: str) -> None:
    """Track ``client_ip`` and raise if the user exceeds ``device_limit``.

    ``device_limit`` of ``None`` or ``0`` means unlimited. An IP already in the
    active window always passes even when at the cap (returning device).
    """
    from fastapi import HTTPException

    limit = getattr(dbuser, "device_limit", None)
    if not limit or limit <= 0:
        return
    if _is_infrastructure_ip(client_ip):
        return

    now = datetime.utcnow()
    ips = _client_device_ips(_prune(_parse_ips(getattr(dbuser, "device_ips", None)), now))

    if client_ip in ips:
        ips[client_ip] = now.isoformat()
        dbuser.device_ips = json.dumps(ips)
        if db is not None:
            db.commit()
        return

    if len(ips) >= int(limit):
        raise HTTPException(
            status_code=403,
            detail=f"Device limit reached ({limit} concurrent devices)",
        )

    ips[client_ip] = now.isoformat()
    dbuser.device_ips = json.dumps(ips)
    if db is not None:
        db.commit()
