"""Auto-provision proxy types required by the SigmaGuard client API."""
from typing import Iterable

from sqlalchemy.exc import IntegrityError

from app import feature_flags
from app.db.models import Proxy, User
from app.models.proxy import ProxySettings, ProxyTypes


def required_app_proxy_types() -> Iterable[ProxyTypes]:
    """Proxy kinds an app user must hold to receive ``protocol_materials``."""
    types = [
        ProxyTypes.VLESS,
        ProxyTypes.WireGuard,
        ProxyTypes.Hysteria2,
        ProxyTypes.TUIC,
        ProxyTypes.AnyTLS,
    ]
    if feature_flags.is_enabled("client_ss2022"):
        types.append(ProxyTypes.Shadowsocks)
    return types


def _default_settings(proxy_type: ProxyTypes) -> dict:
    if proxy_type is ProxyTypes.Shadowsocks and feature_flags.is_enabled("client_ss2022"):
        from app.models.proxy import ShadowsocksMethods

        return ProxySettings.from_dict(
            proxy_type,
            {"method": ShadowsocksMethods.BLAKE3_AES_256_GCM.value},
        ).dict(no_obj=True)
    return ProxySettings.from_dict(proxy_type, {}).dict(no_obj=True)


def ensure_app_proxies(db, dbuser: User) -> bool:
    """Add missing app proxies on a portal-enabled user. Returns True if changed."""
    if not dbuser.portal_enabled:
        return False
    existing = {ProxyTypes(p.type) for p in dbuser.proxies}
    changed = False
    for proxy_type in required_app_proxy_types():
        if proxy_type in existing:
            continue
        dbuser.proxies.append(
            Proxy(
                type=proxy_type.value,
                settings=_default_settings(proxy_type),
            )
        )
        changed = True
    if changed:
        try:
            db.commit()
            db.refresh(dbuser)
        except IntegrityError:
            # Concurrent enable already inserted the same (user, type).
            db.rollback()
            db.refresh(dbuser)
            return False
    return changed
