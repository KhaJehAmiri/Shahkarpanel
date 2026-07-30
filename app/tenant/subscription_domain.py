"""Reseller branding domain → subscription URL / nginx endpoint."""
from __future__ import annotations

import re
from typing import Optional, TYPE_CHECKING
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.db import crud
from app.db.models import Admin, BrandingSettings, SubscriptionEndpoint, User
from config import XRAY_SUBSCRIPTION_PATH

if TYPE_CHECKING:
    from app.models.user import UserResponse

_RESERVED_SUB_PATHS = frozenset({
    "api",
    "admin",
    "dashboard",
    "portal",
    "docs",
    "redoc",
    "openapi.json",
    "static",
    "assets",
    "_next",
    "login",
    "subscribe",
    ".well-known",
})


def reseller_endpoint_slug(tenant_id: Optional[int]) -> str:
    if tenant_id is None:
        return "branding-global"
    return f"reseller-{int(tenant_id)}"


def _normalize_domain(domain: Optional[str]) -> Optional[str]:
    raw = (domain or "").strip().lower()
    if not raw:
        return None
    # Allow pasting a URL; never treat path/query as part of the hostname.
    if "://" in raw:
        try:
            raw = (urlparse(raw).hostname or "").strip().lower()
        except Exception:
            raw = raw.split("://", 1)[-1]
    # Strip credentials, port, path, query leftovers from bare host input.
    raw = raw.split("@")[-1]
    raw = raw.split("/")[0].split("?")[0].split("#")[0]
    host = raw.split(":")[0].strip(".")
    return host or None


def normalize_sub_path(path: Optional[str], *, default: Optional[str] = None) -> str:
    """Normalize a subscription URI path segment (no leading/trailing slash)."""
    raw = (path or "").strip().strip("/")
    if not raw:
        fallback = (default if default is not None else XRAY_SUBSCRIPTION_PATH) or "sub"
        return str(fallback).strip().strip("/") or "sub"
    if "/" in raw or " " in raw:
        raise ValueError("subscription path must be a single segment like sub or v2ray")
    if not re.fullmatch(r"[a-zA-Z0-9]([a-zA-Z0-9_-]*[a-zA-Z0-9])?", raw):
        raise ValueError(
            "subscription path may only contain letters, digits, underscore, and hyphen"
        )
    if raw.lower() in _RESERVED_SUB_PATHS:
        raise ValueError(f"subscription path «{raw}» is reserved by the panel")
    return raw


def normalize_sub_port(port: Optional[int], *, default: int = 443) -> int:
    if port is None:
        return int(default)
    value = int(port)
    if value < 1 or value > 65535:
        raise ValueError("subscription port must be between 1 and 65535")
    return value


def _xray_inbound_ports() -> dict[int, str]:
    """Map listen port → inbound tag for the local Xray core."""
    found: dict[int, str] = {}
    try:
        from app import xray

        for tag, inbound in (getattr(xray.config, "inbounds_by_tag", None) or {}).items():
            if isinstance(inbound, dict):
                port = inbound.get("port")
            else:
                port = getattr(inbound, "port", None)
            if port is None:
                continue
            try:
                found[int(port)] = str(tag)
            except (TypeError, ValueError):
                continue
    except Exception:
        pass
    return found


def _wireguard_listen_ports(db: Session) -> set[int]:
    ports: set[int] = set()
    try:
        from app.db.models import NodeWireGuard

        for row in db.query(NodeWireGuard).all():
            for attr in (
                "listen_port",
                "awg_listen_port",
                "direct_listen_port",
                "xray_wg_listen_port",
            ):
                value = getattr(row, attr, None)
                if value:
                    try:
                        ports.add(int(value))
                    except (TypeError, ValueError):
                        pass
    except Exception:
        pass
    return ports


class SubscriptionPortConflict(ValueError):
    """Raised when a branding subscription port cannot be used."""

    def __init__(
        self,
        port: int,
        reason: str,
        *,
        inbound_tag: Optional[str] = None,
        suggested: Optional[list[int]] = None,
    ):
        self.port = int(port)
        self.reason = reason  # inbound | wireguard | busy
        self.inbound_tag = inbound_tag
        self.suggested = list(suggested or [])
        hint = ", ".join(str(p) for p in self.suggested[:3]) or "2096"
        if reason == "inbound":
            msg = (
                f"port {self.port} is already used by VPN inbound "
                f"«{inbound_tag or '?'}» — pick another port (e.g. {hint} or 443)"
            )
        elif reason == "wireguard":
            msg = (
                f"port {self.port} is already used by WireGuard — "
                f"pick another port (e.g. {hint} or 443)"
            )
        else:
            msg = (
                f"port {self.port} is already in use on this server — "
                f"pick another port (e.g. {hint} or 443)"
            )
        super().__init__(msg)

    def as_detail(self) -> dict:
        return {
            "code": f"sub_port_{self.reason}",
            "port": self.port,
            "inbound_tag": self.inbound_tag,
            "suggested": self.suggested,
            "message": str(self),
        }


_SUB_PORT_SUGGESTIONS = (2096, 2087, 2053, 2086, 8880, 9443, 10443, 3000, 8444)


def suggested_subscription_ports(db: Session, *, limit: int = 5) -> list[int]:
    blocked = {int(p) for p in blocked_subscription_ports(db)}
    out: list[int] = []
    for port in _SUB_PORT_SUGGESTIONS:
        if port in blocked or port in (80, 443):
            continue
        out.append(port)
        if len(out) >= limit:
            break
    return out


def blocked_subscription_ports(db: Session) -> dict[int, dict]:
    """Ports that must not be used for subscription nginx TLS."""
    blocked: dict[int, dict] = {}
    for port, tag in _xray_inbound_ports().items():
        blocked[int(port)] = {
            "port": int(port),
            "reason": "inbound",
            "inbound_tag": tag,
        }
    for port in _wireguard_listen_ports(db):
        blocked.setdefault(
            int(port),
            {"port": int(port), "reason": "wireguard", "inbound_tag": None},
        )
    return blocked


def assert_subscription_listen_port_available(
    db: Session,
    port: int,
    *,
    host: Optional[str] = None,
) -> None:
    """Reject ports already used by VPN inbounds / WireGuard (causes SSL errors).

    Standard 80/443 are shared with the panel nginx vhost and are always allowed.
    Custom ports must be free so nginx can terminate the real Let's Encrypt cert —
    otherwise clients hit Xray Reality and see a foreign certificate (e.g. yahoo.com).
    """
    port = int(port)
    if port in (80, 443):
        return

    suggested = suggested_subscription_ports(db)
    inbound_ports = _xray_inbound_ports()
    if port in inbound_ports:
        raise SubscriptionPortConflict(
            port,
            "inbound",
            inbound_tag=inbound_ports[port],
            suggested=suggested,
        )

    wg_ports = _wireguard_listen_ports(db)
    if port in wg_ports:
        raise SubscriptionPortConflict(
            port, "wireguard", suggested=suggested
        )

    # Soft check: if something non-nginx is already listening, nginx cannot bind.
    try:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", port))
    except OSError:
        # Port may already be owned by nginx for another subscription host (SNI) — OK.
        try:
            from app.db import crud

            for ep in crud.list_subscription_endpoints(db, enabled_only=True):
                if not ep.listen_port or int(ep.listen_port) != port:
                    continue
                ep_host = (ep.host or "").strip().lower()
                if host and ep_host and ep_host != host:
                    # Another subscription domain already has nginx on this port — fine.
                    return
                if host and ep_host == host:
                    return
            raise SubscriptionPortConflict(
                port, "busy", suggested=suggested
            )
        except SubscriptionPortConflict:
            raise
        except Exception as exc:
            raise SubscriptionPortConflict(
                port, "busy", suggested=suggested
            ) from exc


def domain_from_branding(
    branding: dict | BrandingSettings | None,
    *,
    allow_panel_url: bool = True,
) -> Optional[str]:
    """Resolve the custom subscription hostname from branding.

    ``allow_panel_url=False`` uses only the explicit ``domain`` field — used when
    creating/updating the reseller subscription endpoint so a marketing
    ``panel_url`` (or another panel's host) cannot steal/collide with an
    existing endpoint while the reseller only wanted a brand title.
    """
    if branding is None:
        return None
    if isinstance(branding, BrandingSettings):
        domain = branding.domain
        panel_url = getattr(branding, "panel_url", None)
    else:
        domain = branding.get("domain")
        panel_url = branding.get("panel_url")
    host = _normalize_domain(domain)
    if host:
        return host
    if not allow_panel_url:
        return None
    url = (panel_url or "").strip()
    if not url:
        return None
    if "://" not in url:
        url = f"https://{url}"
    try:
        return _normalize_domain(urlparse(url).hostname)
    except Exception:
        return None


def sub_path_from_branding(
    branding: dict | BrandingSettings | None,
    *,
    default: Optional[str] = None,
) -> str:
    if branding is None:
        return normalize_sub_path(None, default=default)
    if isinstance(branding, BrandingSettings):
        path = getattr(branding, "sub_path", None)
    else:
        path = branding.get("sub_path")
    return normalize_sub_path(path, default=default)


def sub_port_from_branding(
    branding: dict | BrandingSettings | None,
    *,
    default: int = 443,
) -> int:
    if branding is None:
        return normalize_sub_port(None, default=default)
    if isinstance(branding, BrandingSettings):
        port = getattr(branding, "sub_port", None)
    else:
        port = branding.get("sub_port")
    return normalize_sub_port(port, default=default)


def public_base_url_for(host: str, port: int) -> str:
    host = _normalize_domain(host) or ""
    if port == 443:
        return f"https://{host}"
    if port == 80:
        return f"http://{host}"
    return f"https://{host}:{int(port)}"


def sample_subscription_url(
    host: str,
    *,
    path: str = "sub",
    port: int = 443,
    token: str = "<token>",
) -> str:
    base = public_base_url_for(host, port).rstrip("/")
    prefix = normalize_sub_path(path)
    return f"{base}/{prefix}/{token}/"


def get_reseller_subscription_endpoint(
    db: Session,
    tenant_id: Optional[int],
) -> Optional[SubscriptionEndpoint]:
    ep = crud.get_subscription_endpoint_by_slug(db, reseller_endpoint_slug(tenant_id))
    if ep and ep.enabled and (ep.host or "").strip():
        return ep
    return None


def tenant_id_for_user(db: Session, user: "UserResponse | User") -> Optional[int]:
    admin_id = getattr(user, "admin_id", None)
    if admin_id is None and getattr(user, "username", None):
        row = crud.get_user(db, user.username)
        admin_id = getattr(row, "admin_id", None) if row else None
    if admin_id is None:
        return None
    admin = db.query(Admin).filter(Admin.id == admin_id).first()
    return getattr(admin, "tenant_id", None) if admin else None


def ensure_reseller_subscription_endpoint(
    db: Session,
    tenant_id: Optional[int],
    domain: Optional[str],
    *,
    sub_path: Optional[str] = None,
    sub_port: Optional[int] = None,
) -> Optional[SubscriptionEndpoint]:
    """Create/update/disable the subscription endpoint for a branding domain."""
    host = _normalize_domain(domain)
    slug = reseller_endpoint_slug(tenant_id)
    ep = crud.get_subscription_endpoint_by_slug(db, slug)
    default = crud.get_default_subscription_endpoint(db)
    default_path = (
        (default.path_prefix if default else None) or XRAY_SUBSCRIPTION_PATH
    )
    path_prefix = normalize_sub_path(sub_path, default=default_path)
    listen_port = normalize_sub_port(sub_port, default=443)

    if not host:
        if ep is not None:
            ep.enabled = False
            ep.host = None
            ep.public_base_url = ""
            db.commit()
            db.refresh(ep)
            try:
                from app.subscription.format_companions import (
                    ensure_format_companions_for_endpoint,
                )

                ensure_format_companions_for_endpoint(db, ep)
            except Exception:
                pass
        return None

    assert_subscription_listen_port_available(db, listen_port, host=host)

    # Avoid colliding with another endpoint's host+path.
    conflict = crud.get_subscription_endpoint_by_host_path(db, host, path_prefix)
    if conflict is not None and (ep is None or conflict.id != ep.id):
        raise ValueError(
            f"Domain {host}/{path_prefix} is already used by subscription endpoint «{conflict.slug}»"
        )

    payload = {
        "slug": slug,
        "host": host,
        "path_prefix": path_prefix,
        "public_base_url": public_base_url_for(host, listen_port),
        "listen_port": listen_port,
        "inbound_tag": None,
        "export_mode": "full",
        "format_default": default.format_default if default else None,
        "legacy_panel_id": None,
        "enabled": True,
    }
    if ep is None:
        ep = crud.create_subscription_endpoint(db, payload)
    else:
        ep = crud.update_subscription_endpoint(db, ep, payload)

    try:
        from app.subscription.format_companions import ensure_format_companions_for_endpoint

        ensure_format_companions_for_endpoint(db, ep)
    except Exception:
        pass

    nginx_applied = False
    nginx_message = ""
    try:
        from app.services.edge_proxy import sync_subscription_legacy_nginx

        sync_result = sync_subscription_legacy_nginx(db) or {}
        nginx_applied = bool(sync_result.get("applied"))
        nginx_message = str(sync_result.get("message") or "").strip()
    except Exception as exc:
        nginx_message = str(exc)

    # ACME can take a long time / fail until DNS is ready — never block branding save.
    try:
        import threading
        from app.db import GetDB
        from app.services.edge_proxy import ensure_subscription_domain_ssl

        host_for_ssl = host

        def _ssl_bg():
            try:
                with GetDB() as ssl_db:
                    ensure_subscription_domain_ssl(ssl_db, host_for_ssl)
            except Exception:
                pass

        threading.Thread(target=_ssl_bg, name=f"branding-ssl-{host}", daemon=True).start()
    except Exception:
        pass

    try:
        from app import app as fastapi_app
        from app.routers import api_router
        from app.subscription.route_registry import refresh_subscription_routes

        refresh_subscription_routes(fastapi_app, api_router)
    except Exception:
        pass

    if host and not nginx_applied:
        detail = nginx_message or "nginx reconcile did not apply"
        # Strip ANSI color codes from host script output for API clients.
        detail = re.sub(r"\x1b\[[0-9;]*m", "", detail).strip()
        raise ValueError(
            "Domain saved in the database, but host nginx is not serving it yet "
            f"({detail}). Install/fix nginx (shahkar https) then save branding again, "
            "or run: sudo scripts/reconcile_subscription_nginx.sh --apply"
        )

    return ep


def sync_branding_subscription_domain(
    db: Session,
    tenant_id: Optional[int],
) -> Optional[SubscriptionEndpoint]:
    row = (
        db.query(BrandingSettings)
        .filter(
            BrandingSettings.tenant_id.is_(None)
            if tenant_id is None
            else BrandingSettings.tenant_id == tenant_id
        )
        .first()
    )
    return ensure_reseller_subscription_endpoint(
        db,
        tenant_id,
        # Only the explicit branding.domain claims a subscription host.
        # panel_url must not invent a domain claim (resellers without a custom
        # domain still save panel_title / sub_profile_title).
        domain_from_branding(row, allow_panel_url=False),
        sub_path=getattr(row, "sub_path", None) if row else None,
        sub_port=getattr(row, "sub_port", None) if row else None,
    )
