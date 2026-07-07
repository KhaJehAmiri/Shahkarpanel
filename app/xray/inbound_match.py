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


def ss_method_for_inbound_tag(tag: str) -> str | None:
    from app import xray

    inbound = xray.config.inbounds_by_tag.get(tag) or {}
    method = (inbound.get("ss_method") or "").strip()
    return method or None


def align_shadowsocks_from_inbounds(proxies: dict, inbounds: dict) -> None:
    """Set SS cipher from the first selected inbound (inbound is source of truth)."""
    from app.models.proxy import ProxyTypes, ShadowsocksSettings

    ss_key = ProxyTypes.Shadowsocks
    if ss_key not in proxies and "shadowsocks" not in proxies:
        return

    key = ss_key if ss_key in proxies else "shadowsocks"
    tags = inbounds.get(ss_key) or inbounds.get("shadowsocks") or []
    if not tags:
        return

    method = ss_method_for_inbound_tag(tags[0])
    if not method:
        return

    raw = proxies[key]
    if isinstance(raw, ShadowsocksSettings):
        settings = raw
    else:
        settings = ShadowsocksSettings.from_dict(ss_key, raw if isinstance(raw, dict) else {})

    current = settings.method.value if hasattr(settings.method, "value") else str(settings.method)
    if is_ss2022(method) == is_ss2022(current):
        return

    settings.method = method
    if isinstance(raw, dict):
        proxies[key] = settings.model_dump(mode="json")
    else:
        proxies[key] = settings


def repair_shadowsocks_proxy_settings(settings: dict, inbound_tags: list[str]) -> dict | None:
    """Return updated SS settings when cipher family mismatches assigned inbounds."""
    from app.models.proxy import ShadowsocksSettings

    if not inbound_tags:
        return None

    method = ss_method_for_inbound_tag(inbound_tags[0])
    if not method:
        return None

    current = (settings or {}).get("method") or ""
    if is_ss2022(method) == is_ss2022(current):
        return None

    updated = ShadowsocksSettings.from_dict(
        ProxyTypes.Shadowsocks,
        {**(settings or {}), "method": method},
    )
    return updated.model_dump(mode="json")
