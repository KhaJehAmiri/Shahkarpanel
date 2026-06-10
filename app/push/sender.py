"""Deliver push notifications to registered SigmaGuard devices.

Uses FCM HTTP v1 when ``FCM_SERVICE_ACCOUNT_JSON`` is set, otherwise the legacy
``FCM_SERVER_KEY`` endpoint. APNs uses JWT auth when ``APNS_KEY_PATH`` is set.
When credentials are missing, calls are logged and skipped (no crash).
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

import jwt
import requests

from app import feature_flags, logger
from config import (
    APNS_BUNDLE_ID,
    APNS_KEY_ID,
    APNS_KEY_PATH,
    APNS_TEAM_ID,
    APNS_USE_SANDBOX,
    FCM_SERVER_KEY,
    FCM_SERVICE_ACCOUNT_JSON,
)


def _fcm_legacy(token: str, title: str, body: str, data: Optional[dict]) -> bool:
    if not FCM_SERVER_KEY:
        return False
    payload: Dict[str, Any] = {
        "to": token,
        "notification": {"title": title, "body": body},
        "priority": "high",
    }
    if data:
        payload["data"] = data
    try:
        r = requests.post(
            "https://fcm.googleapis.com/fcm/send",
            headers={
                "Authorization": f"key={FCM_SERVER_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=10,
        )
        if r.ok:
            return True
        logger.warning("FCM legacy push failed: %s %s", r.status_code, r.text[:200])
    except Exception as exc:
        logger.warning("FCM legacy push error: %s", exc)
    return False


def _fcm_v1(token: str, title: str, body: str, data: Optional[dict]) -> bool:
    if not FCM_SERVICE_ACCOUNT_JSON:
        return False
    try:
        sa = json.loads(FCM_SERVICE_ACCOUNT_JSON)
        project_id = sa["project_id"]
        now = int(time.time())
        assertion = jwt.encode(
            {
                "iss": sa["client_email"],
                "sub": sa["client_email"],
                "aud": "https://oauth2.googleapis.com/token",
                "iat": now,
                "exp": now + 3600,
                "scope": "https://www.googleapis.com/auth/firebase.messaging",
            },
            sa["private_key"],
            algorithm="RS256",
        )
        tok = requests.post(
            "https://oauth2.googleapis.com/token",
            data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
            timeout=10,
        )
        if not tok.ok:
            logger.warning("FCM OAuth failed: %s", tok.text[:200])
            return False
        access = tok.json().get("access_token")
        msg: Dict[str, Any] = {
            "message": {
                "token": token,
                "notification": {"title": title, "body": body},
            }
        }
        if data:
            msg["message"]["data"] = {k: str(v) for k, v in data.items()}
        r = requests.post(
            f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send",
            headers={"Authorization": f"Bearer {access}", "Content-Type": "application/json"},
            json=msg,
            timeout=10,
        )
        if r.ok:
            return True
        logger.warning("FCM v1 push failed: %s %s", r.status_code, r.text[:200])
    except Exception as exc:
        logger.warning("FCM v1 push error: %s", exc)
    return False


def _apns_jwt() -> Optional[str]:
    if not (APNS_KEY_PATH and APNS_KEY_ID and APNS_TEAM_ID):
        return None
    try:
        with open(APNS_KEY_PATH) as f:
            key = f.read()
        now = int(time.time())
        return jwt.encode(
            {"iss": APNS_TEAM_ID, "iat": now},
            key,
            algorithm="ES256",
            headers={"alg": "ES256", "kid": APNS_KEY_ID},
        )
    except Exception as exc:
        logger.warning("APNs JWT error: %s", exc)
        return None


def _apns(token: str, title: str, body: str, data: Optional[dict]) -> bool:
    auth = _apns_jwt()
    if not auth or not APNS_BUNDLE_ID:
        return False
    host = (
        "https://api.sandbox.push.apple.com"
        if APNS_USE_SANDBOX
        else "https://api.push.apple.com"
    )
    payload: Dict[str, Any] = {
        "aps": {"alert": {"title": title, "body": body}, "sound": "default"},
    }
    if data:
        payload.update(data)
    try:
        r = requests.post(
            f"{host}/3/device/{token}",
            headers={
                "authorization": f"bearer {auth}",
                "apns-topic": APNS_BUNDLE_ID,
                "apns-push-type": "alert",
                "apns-priority": "10",
            },
            json=payload,
            timeout=10,
        )
        if r.status_code == 200:
            return True
        logger.warning("APNs push failed: %s %s", r.status_code, r.text[:200])
    except Exception as exc:
        logger.warning("APNs push error: %s", exc)
    return False


def _send_one(platform: Optional[str], token: str, title: str, body: str, data: Optional[dict]) -> bool:
    plat = (platform or "").lower()
    if plat in ("android", "fcm"):
        if FCM_SERVICE_ACCOUNT_JSON:
            return _fcm_v1(token, title, body, data)
        return _fcm_legacy(token, title, body, data)
    if plat in ("ios", "apns"):
        return _apns(token, title, body, data)
    # Unknown platform — try FCM then APNs.
    if FCM_SERVICE_ACCOUNT_JSON or FCM_SERVER_KEY:
        return _fcm_v1(token, title, body, data) or _fcm_legacy(token, title, body, data)
    return _apns(token, title, body, data)


def send_to_devices(
    devices: List[Any],
    title: str,
    body: str,
    data: Optional[dict] = None,
) -> int:
    """Send to a list of ``ClientDevice`` rows. Returns count of successful sends."""
    if not feature_flags.is_enabled("client_push"):
        return 0
    sent = 0
    for dev in devices:
        if _send_one(dev.platform, dev.token, title, body, data):
            sent += 1
    return sent


def send_to_user(
    db,
    user_id: int,
    title: str,
    body: str,
    data: Optional[dict] = None,
) -> int:
    """Send push to all devices registered for ``user_id``."""
    from app.db.models import ClientDevice

    if not feature_flags.is_enabled("client_push"):
        return 0
    devices = db.query(ClientDevice).filter(ClientDevice.user_id == user_id).all()
    return send_to_devices(devices, title, body, data)
