"""Match product inbounds to a user's proxy credentials (SS legacy vs SS-2022)."""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.models.proxy import ProxyTypes
from xray_api.types.account import is_ss2022


def _settings_dict(proxy_settings: Any) -> Dict:
    if proxy_settings is None:
        return {}
    if hasattr(proxy_settings, "model_dump"):
        return proxy_settings.model_dump()
    if isinstance(proxy_settings, dict):
        return proxy_settings
    return {}


def inbound_matches_proxy(
    proxy_type: ProxyTypes | str,
    inbound_tag: str,
    proxy_settings: Any,
    *,
    inbound_meta: Optional[dict] = None,
) -> bool:
    """Return whether ``inbound_tag`` is valid for this user's proxy settings."""
    ptype = proxy_type if isinstance(proxy_type, ProxyTypes) else ProxyTypes(str(proxy_type))
    if ptype != ProxyTypes.Shadowsocks:
        return True

    from app import xray

    inbound = inbound_meta or xray.config.inbounds_by_tag.get(inbound_tag, {})
    in_method = inbound.get("ss_method") or ""
    user_method = _settings_dict(proxy_settings).get("method") or ""
    return is_ss2022(in_method) == is_ss2022(user_method)


def filter_inbound_tags(
    proxy_type: ProxyTypes | str,
    tags: list[str],
    proxy_settings: Any,
) -> list[str]:
    return [t for t in tags if inbound_matches_proxy(proxy_type, t, proxy_settings)]
