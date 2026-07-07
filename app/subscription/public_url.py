"""Build the public subscription URL clients must import (never localhost)."""
from __future__ import annotations

import re
from typing import Optional, TYPE_CHECKING

from fastapi import Request

from app.utils.system import get_public_ip

if TYPE_CHECKING:
    from app.db.models import SubscriptionEndpoint
    from app.models.user import UserResponse
from config import (
    PANEL_PUBLIC_ADDRESS,
    UVICORN_PORT,
    XRAY_SUBSCRIPTION_PATH,
    XRAY_SUBSCRIPTION_URL_PREFIX,
)


_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")


def _extract_token(subscription_url: str, path_prefix: str | None = None) -> str:
    if not subscription_url:
        return ""
    prefix = path_prefix or XRAY_SUBSCRIPTION_PATH
    m = re.search(rf"/{re.escape(prefix)}/([^/?#]+)", subscription_url)
    if m:
        return m.group(1)
    m = re.search(r"/([^/?#]+)/?$", subscription_url.rstrip("/"))
    return m.group(1) if m else ""


def _user_db_id(user: "UserResponse") -> int | None:
    uid = getattr(user, "id", None)
    if uid:
        return int(uid)
    from app.db import GetDB, crud

    with GetDB() as db:
        row = crud.get_user(db, user.username)
        return row.id if row else None


def _token_for_endpoint(user: "UserResponse", endpoint: Optional["SubscriptionEndpoint"]) -> str:
    from app.db import GetDB, crud

    user_id = _user_db_id(user)
    if endpoint and user_id:
        with GetDB() as db:
            aliases = crud.list_subscription_token_aliases_for_user(db, user_id)
            for alias in aliases:
                if alias.endpoint_id == endpoint.id:
                    return alias.token
    if getattr(user, "sub_token", None):
        return user.sub_token
    raw = (user.subscription_url or "").strip()
    return _extract_token(raw) or raw.split("/")[-1].strip("/")


def _panel_slug_candidates(ep: "SubscriptionEndpoint") -> set[str]:
    from app.migration.three_x_ui import _TAG_SAFE

    candidates: set[str] = set()
    for raw in (ep.slug, ep.legacy_panel_id):
        if raw:
            candidates.add(_TAG_SAFE.sub("-", str(raw).strip()).strip("-") or str(raw))
    return candidates


def _inbound_matches_panel(inbound_tag: str, panel_ep: "SubscriptionEndpoint") -> bool:
    candidates = _panel_slug_candidates(panel_ep)
    return any(inbound_tag == c or inbound_tag.startswith(f"{c}-") for c in candidates)


def _token_for_serving(
    user: "UserResponse",
    serving_ep: "SubscriptionEndpoint",
    aliases: list,
) -> str | None:
    """Return the subscription token to embed in a link for ``serving_ep``.

    Migrated users keep their original ``SubscriptionTokenAlias`` (3x-ui
    subId) even when ``serving_ep`` is a per-inbound override row — the alias
    is stored against the panel-wide endpoint, but the link must use the
    override's Listen Domain / URI Path.
    """
    for alias in aliases:
        if alias.endpoint_id == serving_ep.id:
            return alias.token
    inbound_tag = (serving_ep.inbound_tag or "").strip()
    if inbound_tag:
        for alias in aliases:
            panel_ep = alias.endpoint
            if panel_ep and _inbound_matches_panel(inbound_tag, panel_ep):
                return alias.token
    if getattr(user, "sub_token", None):
        return user.sub_token
    raw = (user.subscription_url or "").strip()
    return _extract_token(raw) or None


def _serving_endpoint_for_panel(
    db,
    panel_ep: "SubscriptionEndpoint",
    user_tags: set[str],
):
    """Best endpoint (override preferred) for this panel given the user's inbounds."""
    from app.subscription.endpoint_resolver import resolve_endpoint_for_inbound_tag

    matching = [t for t in user_tags if _inbound_matches_panel(t, panel_ep)]
    if not matching:
        return panel_ep
    override = None
    fallback = None
    for tag in matching:
        resolved = resolve_endpoint_for_inbound_tag(db, tag)
        if not resolved:
            continue
        if resolved.inbound_tag:
            override = resolved
            break
        fallback = resolved
    return override or fallback or panel_ep


def _primary_serving_and_token(
    user: "UserResponse",
    db,
) -> tuple["SubscriptionEndpoint | None", str | None]:
    """Resolve the one subscription link this user should actually use."""
    from app.db import crud
    from app.subscription.endpoint_resolver import resolve_endpoint_for_inbound_tag

    user_id = _user_db_id(user)
    user_tags = _user_inbound_tags(user)
    aliases = (
        crud.list_subscription_token_aliases_for_user(db, user_id) if user_id else []
    )

    if aliases:
        for alias in aliases:
            panel_ep = alias.endpoint
            if not panel_ep or not panel_ep.enabled:
                continue
            serving = _serving_endpoint_for_panel(db, panel_ep, user_tags)
            return serving, alias.token

    if user_tags:
        for tag in sorted(user_tags):
            ep = resolve_endpoint_for_inbound_tag(db, tag)
            if ep:
                token = _token_for_serving(user, ep, aliases)
                return ep, token

    default_ep = crud.get_default_subscription_endpoint(db)
    token = _token_for_endpoint(user, default_ep)
    return default_ep, token


def public_subscription_url(
    user: "UserResponse",
    request: Optional[Request] = None,
    *,
    request_token: Optional[str] = None,
    endpoint: Optional["SubscriptionEndpoint"] = None,
    inbound_tag: Optional[str] = None,
) -> str:
    """Absolute subscription URL reachable from user devices."""
    from app.db import GetDB, crud

    ep = endpoint
    if ep is None and inbound_tag:
        with GetDB() as db:
            for row in crud.list_subscription_endpoints(db, enabled_only=True):
                if row.inbound_tag == inbound_tag and row.export_mode == "inbound_only":
                    ep = row
                    break

    token = request_token
    if ep is None and inbound_tag is None and token is None:
        with GetDB() as db:
            ep, auto_token = _primary_serving_and_token(user, db)
            if auto_token:
                token = auto_token

    base_url = (ep.public_base_url or "").strip() if ep else ""
    if base_url and _SCHEME_RE.match(base_url):
        token = token or _token_for_endpoint(user, ep)
        base = base_url.rstrip("/")
        return f"{base}/{token}/"

    if ep and (ep.host or "").strip():
        # Listen Domain is set but Reverse Proxy URI is blank or missing a
        # scheme (some legacy migrated rows only ever stored a bare
        # "domain.tld" / "domain.tld/json" string here) — derive a proper
        # absolute URL from host/listen_port/path_prefix instead, matching
        # exactly what sync_subscription_legacy_nginx actually serves (plain
        # HTTP on the endpoint's own listen_port, path = /{path_prefix}/) so
        # the link is both domain-correct AND actually reachable. Previously
        # ep.host was only consulted for host-header request routing
        # (resolve_subscription_endpoint), never when building the link
        # handed to admins/clients, so setting just a Listen Domain silently
        # had no visible effect and pre-existing schemeless rows produced a
        # broken link once shown directly (e.g. via absoluteUrl() on the
        # dashboard, which mis-treats a schemeless "domain.tld/token" as a
        # panel-relative path).
        token = token or _token_for_endpoint(user, ep)
        port_suffix = f":{ep.listen_port}" if ep.listen_port else ""
        prefix = (ep.path_prefix or XRAY_SUBSCRIPTION_PATH).strip("/")
        # Legacy 3x-ui subscription ports (e.g. 2096) use HTTPS; browsers and
        # clients expect TLS on the dedicated sub port (see migration subURI).
        port = int(ep.listen_port) if ep.listen_port else 0
        scheme = "https" if port and port not in (80,) else "http"
        return f"{scheme}://{ep.host}{port_suffix}/{prefix}/{token}/"

    raw = (user.subscription_url or "").strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        if ep and ep.path_prefix and ep.path_prefix != XRAY_SUBSCRIPTION_PATH:
            token = token or _token_for_endpoint(user, ep)
            prefix = (XRAY_SUBSCRIPTION_URL_PREFIX or "").strip().rstrip("/")
            if prefix:
                return f"{prefix}/{ep.path_prefix}/{token}/"
        return raw if raw.endswith("/") else f"{raw}/"

    token = (token or "").strip() or _extract_token(raw)
    if not token and raw and "/" not in raw:
        token = raw
    if not token and ep:
        token = _token_for_endpoint(user, ep)

    path_prefix = ep.path_prefix if ep else XRAY_SUBSCRIPTION_PATH

    prefix = (XRAY_SUBSCRIPTION_URL_PREFIX or "").strip().rstrip("/")
    if prefix:
        return f"{prefix}/{path_prefix}/{token}/"

    public_address = (PANEL_PUBLIC_ADDRESS or "").strip().rstrip("/")
    if public_address:
        return f"{public_address}/{path_prefix}/{token}/"

    ip = get_public_ip()
    if ip and ip != "127.0.0.1":
        return f"http://{ip}:{UVICORN_PORT}/{path_prefix}/{token}/"

    if request is not None:
        base = str(request.base_url).rstrip("/")
        return f"{base}/{path_prefix}/{token}/"

    return f"/{path_prefix}/{token}/"


def _user_inbound_tags(user: "UserResponse") -> set[str]:
    tags: set[str] = set()
    for row in (getattr(user, "inbounds", None) or {}).values():
        tags.update(row or [])
    return tags


def list_user_subscription_urls(user: "UserResponse", request: Optional[Request] = None) -> list[dict]:
    """URLs this user should actually use — not every endpoint in the panel.

    Migrated users get exactly the link(s) for panels they have an alias on,
    built from the per-inbound Listen Domain override (when set) plus their
    preserved ``SubscriptionTokenAlias`` token. Unrelated panel endpoints,
    json/clash format variants, and the generic panel-default IP link are
    omitted unless there is no better match.
    """
    from app.db import GetDB, crud

    user_tags = _user_inbound_tags(user)
    urls: list[dict] = []
    seen: set[str] = set()

    def _append(ep, token: str | None, *, recommended: bool = True) -> None:
        if not ep or not token:
            return
        url = public_subscription_url(user, request, endpoint=ep, request_token=token)
        if url in seen:
            return
        seen.add(url)
        from app.subscription.userinfo import subscription_client_import_url

        urls.append(
            {
                "label": ep.slug,
                "slug": ep.slug,
                "url": url,
                "import_url": subscription_client_import_url(url, user),
                "export_mode": ep.export_mode,
                "inbound_tag": ep.inbound_tag,
                "recommended": recommended,
            }
        )

    with GetDB() as db:
        user_id = _user_db_id(user)
        aliases = (
            crud.list_subscription_token_aliases_for_user(db, user_id) if user_id else []
        )

        if aliases:
            for alias in aliases:
                panel_ep = alias.endpoint
                if not panel_ep or not panel_ep.enabled:
                    continue
                serving = _serving_endpoint_for_panel(db, panel_ep, user_tags)
                _append(serving, alias.token)
        elif user_tags:
            for tag in sorted(user_tags):
                from app.subscription.endpoint_resolver import resolve_endpoint_for_inbound_tag

                ep = resolve_endpoint_for_inbound_tag(db, tag)
                if not ep:
                    continue
                token = _token_for_serving(user, ep, aliases)
                _append(ep, token)

        if not urls:
            ep, token = _primary_serving_and_token(user, db)
            _append(ep, token)

    return sorted(urls, key=lambda u: not u["recommended"])
