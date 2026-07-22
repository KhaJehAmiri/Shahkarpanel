"""Account quota / expiry metadata for VPN client apps (subscription-userinfo)."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING
from urllib.parse import quote, urldefrag

from app.subscription.share import encode_title
from app.utils.system import readable_size
from config import SUB_PROFILE_TITLE, SUB_PROFILE_TITLE_DYNAMIC, SUB_SUPPORT_URL, SUB_UPDATE_INTERVAL

if TYPE_CHECKING:
    from app.models.user import UserResponse


def get_subscription_user_info(user: "UserResponse") -> dict[str, int]:
    """Traffic + expiry fields for the subscription-userinfo HTTP header."""
    used = int(user.used_traffic or 0)
    upload = min(int(getattr(user, "used_traffic_up", 0) or 0), used)
    download = used - upload
    return {
        "upload": upload,
        "download": download,
        "total": int(user.data_limit) if user.data_limit is not None else 0,
        "expire": int(user.expire) if user.expire is not None else 0,
    }


def format_subscription_userinfo(user: "UserResponse") -> str:
    return "; ".join(f"{key}={val}" for key, val in get_subscription_user_info(user).items())


def _traffic_summary(user: "UserResponse") -> str:
    used = int(user.used_traffic or 0)
    if user.data_limit is not None:
        limit = int(user.data_limit)
        left = max(0, limit - used)
        return f"{readable_size(left)} left / {readable_size(limit)}"
    return f"{readable_size(used)} used"


def _expiry_summary(user: "UserResponse") -> str:
    if not user.expire:
        return ""
    remaining = int(user.expire) - int(time.time())
    if remaining <= 0:
        return "expired"
    days = remaining // 86400
    if days >= 1:
        return f"{days}d left"
    hours = (remaining % 86400) // 3600
    return f"{hours}h left" if hours else "<1h left"


def format_subscription_profile_title(
    user: "UserResponse",
    *,
    brand: str | None = None,
) -> str:
    """Human-readable subscription group title shown in client apps.

    ``brand`` overrides the env default (tenant ``sub_profile_title`` /
    ``panel_title`` from branding settings).
    """
    effective = (brand if brand is not None else SUB_PROFILE_TITLE) or ""
    effective = effective.strip()
    if not SUB_PROFILE_TITLE_DYNAMIC:
        return effective or SUB_PROFILE_TITLE or user.username

    parts: list[str] = []
    if effective and effective.lower() not in {user.username.lower(), "subscription"}:
        parts.append(effective)
    parts.append(user.username)
    parts.append(_traffic_summary(user))
    expiry = _expiry_summary(user)
    if expiry:
        parts.append(expiry)
    return " · ".join(parts)


def subscription_client_import_url(
    url: str,
    user: "UserResponse",
    *,
    brand: str | None = None,
) -> str:
    """Subscription URL with #fragment title for clients that ignore HTTP headers (v2rayNG)."""
    url = (url or "").strip()
    if not url:
        return ""
    base, _ = urldefrag(url)
    if base and not base.endswith("/"):
        base = f"{base}/"
    title = format_subscription_profile_title(user, brand=brand)
    return f"{base}#{quote(title)}"


def _comment_prefix(config_format: str) -> str | None:
    if config_format in ("v2ray", "clash", "clash-meta", "surge", "loon", "quantumult"):
        return "#"
    return None


def build_subscription_body_preamble(
    user: "UserResponse",
    config_format: str,
    *,
    profile_web_page_url: str = "",
    brand: str | None = None,
    support_url: str | None = None,
) -> str:
    """Embed subscription metadata in the response body for clients that ignore HTTP headers."""
    prefix = _comment_prefix(config_format)
    if not prefix:
        return ""

    lines = [
        f"{prefix}subscription-userinfo: {format_subscription_userinfo(user)}",
        f"{prefix}profile-title: {encode_title(format_subscription_profile_title(user, brand=brand))}",
        f"{prefix}profile-update-interval: {SUB_UPDATE_INTERVAL}",
    ]
    if profile_web_page_url:
        lines.append(f"{prefix}profile-web-page-url: {profile_web_page_url}")
    support = (support_url if support_url is not None else SUB_SUPPORT_URL) or ""
    if support:
        lines.append(f"{prefix}support-url: {support}")
    return "\n".join(lines) + "\n"


def attach_subscription_body_metadata(
    body: str,
    user: "UserResponse",
    config_format: str,
    *,
    as_base64: bool = False,
    profile_web_page_url: str = "",
    brand: str | None = None,
    support_url: str | None = None,
) -> str:
    # Never prepend comment lines before a base64 blob — v2rayNG decodes the
    # whole response body and import silently fails (0 configs).
    if as_base64:
        return body
    preamble = build_subscription_body_preamble(
        user,
        config_format,
        profile_web_page_url=profile_web_page_url,
        brand=brand,
        support_url=support_url,
    )
    if not preamble:
        return body
    return preamble + body
