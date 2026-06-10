"""Build the public subscription URL clients must import (never localhost)."""
from __future__ import annotations

import re
from typing import Optional

from typing import TYPE_CHECKING

from fastapi import Request

from app.utils.system import get_public_ip

if TYPE_CHECKING:
    from app.models.user import UserResponse
from config import (
    PANEL_PUBLIC_ADDRESS,
    UVICORN_PORT,
    XRAY_SUBSCRIPTION_PATH,
    XRAY_SUBSCRIPTION_URL_PREFIX,
)


def _extract_token(subscription_url: str) -> str:
    if not subscription_url:
        return ""
    m = re.search(rf"/{re.escape(XRAY_SUBSCRIPTION_PATH)}/([^/?#]+)", subscription_url)
    return m.group(1) if m else ""


def public_subscription_url(
    user: "UserResponse",
    request: Optional[Request] = None,
    *,
    request_token: Optional[str] = None,
) -> str:
    """Absolute subscription URL reachable from user devices."""
    raw = (user.subscription_url or "").strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw if raw.endswith("/") else f"{raw}/"

    token = (request_token or "").strip() or _extract_token(raw)
    if not token and raw and "/" not in raw:
        token = raw

    prefix = (XRAY_SUBSCRIPTION_URL_PREFIX or "").strip().rstrip("/")
    if prefix:
        return f"{prefix}/{XRAY_SUBSCRIPTION_PATH}/{token}/"

    # Behind the HTTPS reverse proxy the app port is localhost-only, so the
    # panel's public address is the only base reachable from user devices.
    public_address = (PANEL_PUBLIC_ADDRESS or "").strip().rstrip("/")
    if public_address:
        return f"{public_address}/{XRAY_SUBSCRIPTION_PATH}/{token}/"

    ip = get_public_ip()
    if ip and ip != "127.0.0.1":
        return f"http://{ip}:{UVICORN_PORT}/{XRAY_SUBSCRIPTION_PATH}/{token}/"

    if request is not None:
        base = str(request.base_url).rstrip("/")
        return f"{base}/{XRAY_SUBSCRIPTION_PATH}/{token}/"

    return f"/{XRAY_SUBSCRIPTION_PATH}/{token}/"
