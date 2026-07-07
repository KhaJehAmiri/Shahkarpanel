"""Track admin login sessions and support per-user token revocation."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Any, Optional

_SESSIONS_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "admin_sessions.json")
)
_MAX_SESSIONS = 200


def _load() -> dict[str, Any]:
    if not os.path.isfile(_SESSIONS_PATH):
        return {"sessions": [], "revoked_before": {}}
    try:
        with open(_SESSIONS_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return {"sessions": [], "revoked_before": {}}
        raw.setdefault("sessions", [])
        raw.setdefault("revoked_before", {})
        return raw
    except (json.JSONDecodeError, OSError):
        return {"sessions": [], "revoked_before": {}}


def _save(data: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(_SESSIONS_PATH), mode=0o700, exist_ok=True)
    with open(_SESSIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def record_login(username: str, *, ip: str = "", is_sudo: bool = False, iat: Optional[float] = None) -> None:
    ts = float(iat if iat is not None else time.time())
    data = _load()
    sessions = data.get("sessions") or []
    sessions.insert(
        0,
        {
            "username": username,
            "ip": ip,
            "is_sudo": is_sudo,
            "iat": ts,
            "logged_at": datetime.utcfromtimestamp(ts).isoformat() + "Z",
        },
    )
    data["sessions"] = sessions[:_MAX_SESSIONS]
    _save(data)


def list_sessions(limit: int = 100) -> list[dict[str, Any]]:
    data = _load()
    return list((data.get("sessions") or [])[:limit])


def revoke_user_sessions(username: str, *, before: Optional[float] = None) -> None:
    """Invalidate all tokens for ``username`` issued before ``before`` (default: now)."""
    ts = float(before if before is not None else time.time())
    data = _load()
    revoked = data.get("revoked_before") or {}
    prev = float(revoked.get(username) or 0)
    revoked[username] = max(prev, ts)
    data["revoked_before"] = revoked
    _save(data)


def is_token_revoked(username: str, iat: Optional[float]) -> bool:
    if iat is None:
        return False
    data = _load()
    revoked = data.get("revoked_before") or {}
    cutoff = float(revoked.get(username) or 0)
    return float(iat) < cutoff
