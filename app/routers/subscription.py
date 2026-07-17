import re
from distutils.version import LooseVersion
from pathlib import Path as _Path

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db import Session, crud, get_db
from app.db.models import User
from app.dependencies import get_validated_sub, get_subscription_context, resolve_sub_ctx, validate_dates
from app.subscription.endpoint_resolver import SubscriptionRequestContext
from app.models.proxy import ProxyTypes
from app.models.user import SubscriptionUserResponse, UserResponse
from app.subscription.guards import ensure_subscription_config_allowed, subscription_access
from app.subscription.blocked import blocked_message, generate_blocked_subscription
from app.subscription.public_url import public_subscription_url
from app.subscription.quic import user_anytls_link, user_hysteria2_link, user_tuic_link
from app.services.node_pick import pick_node
from app.subscription.share import encode_title, generate_subscription
from app.subscription.userinfo import (
    attach_subscription_body_metadata,
    format_subscription_profile_title,
    format_subscription_userinfo,
)
from app.subscription.wireguard import user_config as build_wireguard_user_config
from app.templates import render_template
from config import (
    SUB_SUPPORT_URL,
    SUB_UPDATE_INTERVAL,
    SUBSCRIPTION_PAGE_TEMPLATE,
    USE_CUSTOM_JSON_DEFAULT,
    USE_CUSTOM_JSON_FOR_HAPP,
    USE_CUSTOM_JSON_FOR_STREISAND,
    USE_CUSTOM_JSON_FOR_V2RAYN,
    USE_CUSTOM_JSON_FOR_V2RAYNG,
    XRAY_SUBSCRIPTION_PATH,
)

client_config = {
    "clash-meta": {"config_format": "clash-meta", "media_type": "text/yaml", "as_base64": False, "reverse": False},
    "sing-box": {"config_format": "sing-box", "media_type": "application/json", "as_base64": False, "reverse": False},
    "clash": {"config_format": "clash", "media_type": "text/yaml", "as_base64": False, "reverse": False},
    "v2ray": {"config_format": "v2ray", "media_type": "text/plain", "as_base64": True, "reverse": False},
    "outline": {"config_format": "outline", "media_type": "application/json", "as_base64": False, "reverse": False},
    "v2ray-json": {"config_format": "v2ray-json", "media_type": "application/json", "as_base64": False,
                   "reverse": False},
    "surge": {"config_format": "surge", "media_type": "text/plain", "as_base64": False, "reverse": False},
    "loon": {"config_format": "loon", "media_type": "text/plain", "as_base64": False, "reverse": False},
    "quantumult": {"config_format": "quantumult", "media_type": "text/plain", "as_base64": False, "reverse": False},
}

router = APIRouter(tags=['Subscription'], prefix=f'/{XRAY_SUBSCRIPTION_PATH}')

# Every export route below hands back live proxy secrets (UUIDs, WireGuard
# private keys, Reality short-ids, etc.). Without this, browsers/CDNs/proxies
# are free to cache the response body — leaking credentials to shared caches
# or later requesters on the same client (AUDIT_FINDINGS.md M7).
NO_STORE_HEADERS = {"Cache-Control": "private, no-store", "Pragma": "no-cache"}


def _subscription_response_headers(
    user: UserResponse,
    request: Request,
    req_token: str,
    *,
    endpoint=None,
) -> dict:
    pub_url = public_subscription_url(user, request, request_token=req_token, endpoint=endpoint)
    return {
        "content-disposition": f'attachment; filename="{user.username}"',
        "profile-web-page-url": pub_url,
        "support-url": SUB_SUPPORT_URL,
        "profile-title": encode_title(format_subscription_profile_title(user)),
        "profile-update-interval": SUB_UPDATE_INTERVAL,
        "subscription-userinfo": format_subscription_userinfo(user),
        **NO_STORE_HEADERS,
    }


def _resolve_subscription_body(
    user: UserResponse,
    *,
    config_format: str,
    as_base64: bool,
    reverse: bool,
    inbound_filter: str | None = None,
    profile_web_page_url: str = "",
) -> tuple[str, dict]:
    """Return subscription body plus access metadata (for blocked profile title)."""
    access = subscription_access(user)
    if not access["config_available"]:
        conf = generate_blocked_subscription(
            block_reason=access["block_reason"],
            config_format=config_format,
            as_base64=as_base64,
            reverse=reverse,
        )
    else:
        conf = generate_subscription(
            user=user,
            config_format=config_format,
            as_base64=as_base64,
            reverse=reverse,
            inbound_filter=inbound_filter,
        )
    conf = attach_subscription_body_metadata(
        conf,
        user,
        config_format,
        as_base64=as_base64,
        profile_web_page_url=profile_web_page_url,
    )
    return conf, access


def _v2ray_json_response(
    user: UserResponse,
    response_headers: dict,
    *,
    reverse: bool = False,
    inbound_filter: str | None = None,
) -> Response:
    conf, access = _resolve_subscription_body(
        user,
        config_format="v2ray-json",
        as_base64=False,
        reverse=reverse,
        inbound_filter=inbound_filter,
        profile_web_page_url=response_headers.get("profile-web-page-url", ""),
    )
    if not access["config_available"]:
        response_headers["profile-title"] = encode_title(blocked_message(access["block_reason"]))
    return Response(content=conf, media_type="application/json", headers=response_headers)


def _v2ray_base64_response(
    user: UserResponse,
    response_headers: dict,
    *,
    inbound_filter: str | None = None,
) -> Response:
    conf, access = _resolve_subscription_body(
        user,
        config_format="v2ray",
        as_base64=True,
        reverse=False,
        inbound_filter=inbound_filter,
        profile_web_page_url=response_headers.get("profile-web-page-url", ""),
    )
    if not access["config_available"]:
        response_headers["profile-title"] = encode_title(blocked_message(access["block_reason"]))
    return Response(content=conf, media_type="text/plain", headers=response_headers)


def _sub_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _enforce_export_guards(db: Session, dbuser, request: Request) -> None:
    """Common device/session-limit gate for every route that hands back live
    connection material (config, .conf files, share links).

    Previously this was only wired into the main multi-format ``/{token}``
    route, so a client could freely rack up unlimited devices/sessions by
    only ever hitting ``/info``, ``/wireguard``, ``/wireguard/prepare``,
    ``/hysteria2``, ``/tuic``, or ``/anytls`` directly — each of those hands
    out equally-live material without ever being counted
    (AUDIT_FINDINGS.md M8). Raises HTTPException(403) if a limit is exceeded.
    """
    from app.utils.device_limit import record_and_check_device_limit
    from app.utils.session_limit import check_session_limit, touch_online

    record_and_check_device_limit(db, dbuser, _sub_client_ip(request))
    # Expired session is renewed by fetching subscription (the client "reconnect").
    try:
        check_session_limit(dbuser)
    except HTTPException as exc:
        if exc.status_code != 403 or "Session time limit" not in str(exc.detail):
            raise
    touch_online(db, dbuser)


def _proxy_settings(dbuser, proxy_type: ProxyTypes) -> dict | None:
    for proxy in dbuser.proxies:
        if proxy.type is proxy_type:
            return proxy.settings or {}
    return None


def _wireguard_user_settings(dbuser) -> dict:
    return _proxy_settings(dbuser, ProxyTypes.WireGuard)


def _attach_subscription_share_links(db: Session, dbuser, payload: dict) -> None:
    """Build formatted share links for the subscribe page.

    Derived from credentials already present in ``/info`` JSON — not gated by
    device/session export guards (those still apply to ``/{token}`` exports).
    """
    hy2_settings = _proxy_settings(dbuser, ProxyTypes.Hysteria2)
    tuic_settings = _proxy_settings(dbuser, ProxyTypes.TUIC)
    anytls_settings = _proxy_settings(dbuser, ProxyTypes.AnyTLS)
    sb_nodes = [n for n in crud.get_singbox_nodes(db) if n.singbox is not None]
    if sb_nodes and (hy2_settings or tuic_settings or anytls_settings):
        preferred_hy2 = None
        preferred_tuic = None
        preferred_anytls = None
        if hy2_settings:
            hy2_nodes = [n for n in sb_nodes if n.singbox.hysteria2_enabled]
            preferred_hy2 = pick_node(hy2_nodes) if hy2_nodes else None
        if tuic_settings:
            tuic_nodes = [n for n in sb_nodes if n.singbox.tuic_enabled]
            preferred_tuic = pick_node(tuic_nodes) if tuic_nodes else None
        if anytls_settings:
            anytls_nodes = [n for n in sb_nodes if n.singbox.anytls_enabled]
            preferred_anytls = pick_node(anytls_nodes) if anytls_nodes else None

        from app.subscription.region_display import node_config_remark, resolve_region_display

        node_items = []
        for n in sb_nodes:
            region_flag, region_name = resolve_region_display(n.region, node_name=n.name)
            item = {
                "id": n.id,
                "name": n.name,
                "address": n.address,
                "region": n.region,
                "region_flag": region_flag,
                "region_name": region_name,
                "latency_ms": n.latency_ms,
                "hysteria2_link": None,
                "tuic_link": None,
                "anytls_link": None,
                "hysteria2_available": bool(n.singbox.hysteria2_enabled),
                "tuic_available": bool(n.singbox.tuic_enabled),
                "anytls_available": bool(n.singbox.anytls_enabled),
            }
            if hy2_settings and n.singbox.hysteria2_enabled:
                item["hysteria2_link"] = user_hysteria2_link(
                    hy2_settings, n, remark=node_config_remark(n, "Hysteria2"),
                    speed_limit_up=dbuser.speed_limit_up,
                    speed_limit_down=dbuser.speed_limit_down,
                )
            if tuic_settings and n.singbox.tuic_enabled:
                item["tuic_link"] = user_tuic_link(
                    tuic_settings, n, remark=node_config_remark(n, "TUIC"),
                    speed_limit_up=dbuser.speed_limit_up,
                    speed_limit_down=dbuser.speed_limit_down,
                )
            if anytls_settings and n.singbox.anytls_enabled:
                item["anytls_link"] = user_anytls_link(
                    anytls_settings, n, remark=node_config_remark(n, "AnyTLS"),
                    speed_limit_up=dbuser.speed_limit_up,
                    speed_limit_down=dbuser.speed_limit_down,
                )
            node_items.append(item)
        payload["singbox_nodes"] = node_items

        if preferred_hy2 and preferred_hy2.singbox:
            payload["hysteria2_link"] = user_hysteria2_link(
                hy2_settings, preferred_hy2,
                remark=node_config_remark(preferred_hy2, "Hysteria2"),
                speed_limit_up=dbuser.speed_limit_up,
                speed_limit_down=dbuser.speed_limit_down,
            )
        if preferred_tuic and preferred_tuic.singbox:
            payload["tuic_link"] = user_tuic_link(
                tuic_settings, preferred_tuic,
                remark=node_config_remark(preferred_tuic, "TUIC"),
                speed_limit_up=dbuser.speed_limit_up,
                speed_limit_down=dbuser.speed_limit_down,
            )
        if preferred_anytls and preferred_anytls.singbox:
            payload["anytls_link"] = user_anytls_link(
                anytls_settings, preferred_anytls,
                remark=node_config_remark(preferred_anytls, "AnyTLS"),
                speed_limit_up=dbuser.speed_limit_up,
                speed_limit_down=dbuser.speed_limit_down,
            )
    wg_settings = _wireguard_user_settings(dbuser)
    if wg_settings:
        wg_nodes = [n for n in crud.get_wireguard_nodes(db) if n.wireguard is not None]
        if wg_nodes:
            from app.subscription.region_display import node_config_remark, resolve_region_display
            from app.subscription.wireguard import user_share_link

            from app.subscription.wireguard import user_config as wg_user_config
            from app.wireguard.sync import amneziawg_enabled, direct_wg_enabled

            preferred = pick_node(wg_nodes)
            node_items = []
            awg_any = False
            direct_any = False
            for n in wg_nodes:
                link = user_share_link(
                    wg_settings, n, variant="plain",
                    remark=node_config_remark(n, "WireGuard"), db=db,
                )
                awg_ok = bool(
                    n.wireguard
                    and amneziawg_enabled(n.wireguard)
                    and wg_user_config(wg_settings, n, variant="awg", db=db)
                )
                direct_link = None
                if n.wireguard and direct_wg_enabled(n.wireguard):
                    direct_link = user_share_link(
                        wg_settings, n, variant="direct",
                        remark=node_config_remark(n, "WireGuard Direct"), db=db,
                    )
                awg_any = awg_any or awg_ok
                direct_any = direct_any or bool(direct_link)
                region_flag, region_name = resolve_region_display(n.region, node_name=n.name)
                node_items.append({
                    "id": n.id,
                    "name": n.name,
                    "address": n.address,
                    "region": n.region,
                    "region_flag": region_flag,
                    "region_name": region_name,
                    "latency_ms": n.latency_ms,
                    "wireguard_uri": link,
                    "awg_available": awg_ok,
                    "wireguard_direct_uri": direct_link,
                })
            payload["wireguard_nodes"] = node_items
            if preferred:
                link = user_share_link(
                    wg_settings, preferred, variant="plain",
                    remark=node_config_remark(preferred, "WireGuard"), db=db,
                )
                if link:
                    payload["wireguard_uri"] = link
                if preferred.wireguard and amneziawg_enabled(preferred.wireguard):
                    if wg_user_config(wg_settings, preferred, variant="awg", db=db):
                        payload["wireguard_awg_available"] = True
                if preferred.wireguard and direct_wg_enabled(preferred.wireguard):
                    direct_link = user_share_link(
                        wg_settings, preferred, variant="direct",
                        remark=node_config_remark(preferred, "WireGuard Direct"), db=db,
                    )
                    if direct_link:
                        payload["wireguard_direct_uri"] = direct_link
            elif awg_any or direct_any:
                if awg_any:
                    payload["wireguard_awg_available"] = True
                if direct_any:
                    payload["wireguard_direct_available"] = True


def _browser_subscribe_redirect_url(
    request: Request,
    token: str,
    *,
    listen_port: int | None = None,
) -> str:
    """Send browser users to the panel HTTPS vhost (443), not the legacy sub port."""
    host_hdr = (request.headers.get("host") or "").strip().lower()
    host_name = host_hdr.split(":")[0] if host_hdr else ""
    port: int | None = None
    if ":" in host_hdr:
        port_str = host_hdr.rsplit(":", 1)[-1]
        if port_str.isdigit():
            port = int(port_str)
    elif listen_port:
        port = int(listen_port)
    if host_name and port and port not in (80, 443):
        return f"https://{host_name}/subscribe/?token={token}"
    return f"/subscribe/?token={token}"


# Many VPN client apps (V2Box, Happ, some HiddifyNext/v2rayNG builds) send a
# generic `Accept: text/html, */*` header on their subscription fetch instead
# of `Accept: application/json` or `text/plain`. If we redirect on Accept
# alone, these clients get an HTML page (or a 302 to it) instead of their
# config and "fail to import" with no useful error. Recognize known client
# UAs up front so they always get their config, regardless of Accept header.
_KNOWN_CLIENT_UA_RE = re.compile(
    r'^(Surge|Loon|Quantumult|Quantumult%20X|[Cc]lash-verge|[Cc]lash[-\.]?[Mm]eta|'
    r'[Ff][Ll][Cc]lash|[Mm]ihomo|[Cc]lash|[Ss]tash|HiddifyNextX|[Vv]2[Bb]ox|'
    r'v2rayN/|v2rayNG/|Happ/)'
)


@router.get("/{token}/")
@router.get("/{token}", include_in_schema=False)
def user_subscription(
    request: Request,
    db: Session = Depends(get_db),
    dbuser: User = Depends(get_validated_sub),
    sub_ctx: SubscriptionRequestContext = Depends(get_subscription_context),
    user_agent: str = Header(default="")
):
    """Provides a subscription link based on the user agent (Clash, V2Ray, etc.)."""
    sub_ctx = resolve_sub_ctx(sub_ctx, request, db)
    user: UserResponse = UserResponse.model_validate(dbuser, context={"skip_default_links": True})
    inbound_filter = sub_ctx.inbound_filter
    endpoint = sub_ctx.endpoint

    accept_header = request.headers.get("Accept", "")
    is_known_client = bool(_KNOWN_CLIENT_UA_RE.match(user_agent)) or bool(
        sub_ctx.format_default and sub_ctx.format_default in client_config
    )
    if "text/html" in accept_header and not is_known_client:
        # Phase 9: prefer the new Next.js subscription page (graphical, with
        # platform tabs) when its static build is present. The page reads the
        # token from the URL and fetches /sub/<token>/info itself.
        next_index = _Path(__file__).parent.parent / 'dashboard-next' / 'out' / 'subscribe' / 'index.html'
        if next_index.is_file():
            token = request.path_params.get('token', '')
            return RedirectResponse(
                url=_browser_subscribe_redirect_url(
                    request,
                    token,
                    listen_port=endpoint.listen_port if endpoint else None,
                ),
                status_code=302,
            )
        return HTMLResponse(
            render_template(
                SUBSCRIPTION_PAGE_TEMPLATE,
                {"user": user, **subscription_access(user)}
            )
        )

    access = subscription_access(user)
    if access["config_available"]:
        ensure_subscription_config_allowed(user)
        _enforce_export_guards(db, dbuser, request)

    crud.update_user_sub(db, dbuser, user_agent)
    req_token = request.path_params.get("token", "")
    response_headers = _subscription_response_headers(
        user, request, req_token, endpoint=endpoint
    )
    if not access["config_available"]:
        response_headers["profile-title"] = encode_title(blocked_message(access["block_reason"]))

    def _format_response(config_format: str, media_type: str, *, as_base64: bool = False, reverse: bool = False):
        conf, _ = _resolve_subscription_body(
            user,
            config_format=config_format,
            as_base64=as_base64,
            reverse=reverse,
            inbound_filter=inbound_filter,
            profile_web_page_url=response_headers.get("profile-web-page-url", ""),
        )
        return Response(content=conf, media_type=media_type, headers=response_headers)

    if sub_ctx.format_default and sub_ctx.format_default in client_config:
        cfg = client_config[sub_ctx.format_default]
        return _format_response(
            cfg["config_format"],
            cfg["media_type"],
            as_base64=cfg["as_base64"],
            reverse=cfg["reverse"],
        )

    if re.match(r'^Surge', user_agent):
        return _format_response("surge", "text/plain")

    if re.match(r'^Loon', user_agent):
        return _format_response("loon", "text/plain")

    if re.match(r'^(Quantumult|Quantumult%20X)', user_agent):
        return _format_response("quantumult", "text/plain")

    if re.match(r'^([Cc]lash-verge|[Cc]lash[-\.]?[Mm]eta|[Ff][Ll][Cc]lash|[Mm]ihomo)', user_agent):
        return _format_response("clash-meta", "text/yaml")

    elif re.match(r'^([Cc]lash|[Ss]tash)', user_agent):
        return _format_response("clash", "text/yaml")

    elif re.match(r'^HiddifyNextX', user_agent):
        return _v2ray_json_response(user, response_headers, inbound_filter=inbound_filter)

    elif re.match(r'^[Vv]2[Bb]ox', user_agent):
        # V2Box imports the base64 share-link list (vless://, vmess://, …).
        # Serving v2ray-json broke subscription import in the app.
        # Finalmask / Xray-native WG: use /sub/<token>/v2ray-json explicitly.
        return _v2ray_base64_response(user, response_headers, inbound_filter=inbound_filter)

    elif re.match(r'^v2rayN/(\d+\.\d+)', user_agent):
        version_str = re.match(r'^v2rayN/(\d+\.\d+)', user_agent).group(1)
        if LooseVersion(version_str) >= LooseVersion("6.40"):
            return _v2ray_json_response(user, response_headers, inbound_filter=inbound_filter)
        if USE_CUSTOM_JSON_DEFAULT or USE_CUSTOM_JSON_FOR_V2RAYN:
            return _v2ray_json_response(user, response_headers, inbound_filter=inbound_filter)
        return _v2ray_base64_response(user, response_headers, inbound_filter=inbound_filter)

    elif re.match(r'^v2rayNG/(\d+\.\d+\.\d+)', user_agent):
        version_str = re.match(r'^v2rayNG/(\d+\.\d+\.\d+)', user_agent).group(1)
        if LooseVersion(version_str) >= LooseVersion("1.8.29"):
            return _v2ray_json_response(user, response_headers, inbound_filter=inbound_filter)
        if LooseVersion(version_str) >= LooseVersion("1.8.18"):
            return _v2ray_json_response(
                user, response_headers, reverse=True, inbound_filter=inbound_filter
            )
        return _v2ray_base64_response(user, response_headers, inbound_filter=inbound_filter)

    elif re.match(r'^Happ/(\d+\.\d+\.\d+)', user_agent):
        version_str = re.match(r'^Happ/(\d+\.\d+\.\d+)', user_agent).group(1)
        if LooseVersion(version_str) >= LooseVersion("1.63.1"):
            return _v2ray_json_response(user, response_headers, inbound_filter=inbound_filter)
        if USE_CUSTOM_JSON_DEFAULT or USE_CUSTOM_JSON_FOR_HAPP:
            return _v2ray_json_response(user, response_headers, inbound_filter=inbound_filter)
        return _v2ray_base64_response(user, response_headers, inbound_filter=inbound_filter)

    else:
        return _v2ray_base64_response(user, response_headers, inbound_filter=inbound_filter)


@router.get("/{token}/info", response_model=SubscriptionUserResponse)
def user_subscription_info(
    request: Request,
    response: Response,
    dbuser: User = Depends(get_validated_sub),
    sub_ctx: SubscriptionRequestContext = Depends(get_subscription_context),
    db: Session = Depends(get_db),
):
    """Retrieves detailed information about the user's subscription."""
    sub_ctx = resolve_sub_ctx(sub_ctx, request, db)
    response.headers.update(NO_STORE_HEADERS)
    user = UserResponse.model_validate(dbuser, context={"skip_default_links": True})
    payload = user.model_dump()
    access = subscription_access(user)
    req_token = request.path_params.get("token", "")
    pub_url = public_subscription_url(
        user, request, request_token=req_token, endpoint=sub_ctx.endpoint
    )
    payload.update(access)
    from app.subscription.userinfo import format_subscription_profile_title, subscription_client_import_url

    payload["subscription_profile_title"] = format_subscription_profile_title(user)
    payload["public_subscription_url"] = pub_url
    payload["client_subscription_url"] = subscription_client_import_url(pub_url, user)
    from app.subscription.public_url import list_user_subscription_urls

    payload["subscription_urls"] = list_user_subscription_urls(user, request) if access["config_available"] else []
    if not access["config_available"]:
        payload["links"] = []
        payload["link_items"] = []
        payload["subscription_url"] = ""
        payload["public_subscription_url"] = ""
        payload["client_subscription_url"] = ""
        payload["subscription_profile_title"] = ""
    else:
        payload["subscription_url"] = pub_url
        from app.subscription.share import collect_v2ray_share_links

        payload["links"] = collect_v2ray_share_links(
            user, inbound_filter=sub_ctx.inbound_filter, reverse=False
        )
        from app.subscription.share import collect_v2ray_share_link_items

        payload["link_items"] = collect_v2ray_share_link_items(
            user, inbound_filter=sub_ctx.inbound_filter, reverse=False
        )
        _attach_subscription_share_links(db, dbuser, payload)
    return SubscriptionUserResponse.model_validate(payload)


@router.get("/{token}/usage")
def user_get_usage(
    dbuser: User = Depends(get_validated_sub),
    start: str = "",
    end: str = "",
    db: Session = Depends(get_db)
):
    """Fetches the usage statistics for the user within a specified date range."""
    start, end = validate_dates(start, end)

    usages = crud.get_user_usages(db, dbuser, start, end)

    return {"usages": usages, "username": dbuser.username}


@router.get("/{token}/wireguard/prepare")
@router.get("/{token}/wireguard/prepare/{node_id}", include_in_schema=False)
def user_wireguard_prepare(
    request: Request,
    dbuser=Depends(get_validated_sub),
    node_id: int = None,
    db: Session = Depends(get_db),
):
    """Clear a learned AWG endpoint so the next connect starts fresh.

    Open this URL in the browser before reconnecting when using a static
    ``.conf`` in Amnezia (no need to re-import the profile).
    """
    ensure_subscription_config_allowed(dbuser)
    _enforce_export_guards(db, dbuser, request)

    settings = _wireguard_user_settings(dbuser)
    if not settings:
        raise HTTPException(status_code=404, detail="No WireGuard configuration for this user")

    nodes = [n for n in crud.get_wireguard_nodes(db) if n.wireguard is not None]
    if node_id is not None:
        nodes = [n for n in nodes if n.id == node_id]
    if not nodes:
        raise HTTPException(status_code=404, detail="No WireGuard node available")

    dbnode = pick_node(nodes, node_id)
    if dbnode is None:
        raise HTTPException(status_code=404, detail="No WireGuard node available")

    from app.wireguard.operations import prepare_awg_peer_for_connect
    from app.wireguard.sync import amneziawg_enabled
    from app.wireguard.transport import WireGuardTransportError

    if not amneziawg_enabled(dbnode.wireguard):
        raise HTTPException(status_code=404, detail="AmneziaWG is not enabled on this node")

    try:
        prepare_awg_peer_for_connect(dbnode, settings.get("public_key"))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WireGuardTransportError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "node": dbnode.name}


@router.get("/{token}/wireguard")
@router.get("/{token}/wireguard/{node_id}", include_in_schema=False)
def user_subscription_wireguard(
    request: Request,
    dbuser=Depends(get_validated_sub),
    node_id: int = None,
    variant: str = "plain",
    db: Session = Depends(get_db),
):
    """Return a wg-quick ``.conf`` for the user, tied to the same token and
    central quota. Issuance is gated on billable status / quota so a
    disabled / limited / expired user does not receive a working config."""
    ensure_subscription_config_allowed(dbuser)
    _enforce_export_guards(db, dbuser, request)

    settings = _wireguard_user_settings(dbuser)
    if not settings:
        raise HTTPException(status_code=404, detail="No WireGuard configuration for this user")

    nodes = [n for n in crud.get_wireguard_nodes(db) if n.wireguard is not None]
    if node_id is not None:
        nodes = [n for n in nodes if n.id == node_id]
    if not nodes:
        raise HTTPException(status_code=404, detail="No WireGuard node available")

    dbnode = pick_node(nodes, node_id)
    if dbnode is None:
        raise HTTPException(status_code=404, detail="No WireGuard node available")
    cfg = dbnode.wireguard
    variant = (variant or "plain").strip().lower()
    if variant not in ("plain", "awg", "direct", "xray_native"):
        raise HTTPException(status_code=422, detail="variant must be plain, awg, direct, or xray_native")

    from app.wireguard.operations import ensure_preshared_key, ensure_user_address
    from app.wireguard.sync import amneziawg_enabled, plain_wg_enabled
    from app.wireguard.wg_manager import autoscale_enabled, create_peer

    if variant == "plain" and plain_wg_enabled(cfg) and autoscale_enabled():
        try:
            result = create_peer(db, dbuser.id, node_id=dbnode.id)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        suffix = ""
        filename = f"{dbuser.username}-{dbnode.name}{suffix}.conf"
        return Response(
            content=result["conf"],
            media_type="text/plain",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                **NO_STORE_HEADERS,
            },
        )

    for proxy in dbuser.proxies:
        if proxy.type is ProxyTypes.WireGuard:
            settings = ensure_preshared_key(db, proxy)
            if variant == "awg" and amneziawg_enabled(cfg):
                if not settings.get("awg_address"):
                    ensure_user_address(db, proxy, cfg.awg_subnet, cfg=cfg)
            elif plain_wg_enabled(cfg) and not settings.get("address"):
                ensure_user_address(db, proxy, cfg.subnet, cfg=cfg)
            settings = proxy.settings or {}
            break

    if variant == "xray_native":
        import json

        from app.wireguard.finalmask_shard import finalmask_client_port
        from app.wireguard.xray_native import (
            build_xray_native_client_config,
            finalmask_client_mtu,
            xray_native_wg_enabled,
        )

        if not xray_native_wg_enabled(cfg):
            raise HTTPException(status_code=404, detail="Xray-native WireGuard is not enabled on this node")
        local_address = settings.get("address")
        if not local_address or not settings.get("private_key") or not cfg.public_key:
            raise HTTPException(status_code=404, detail="No WireGuard configuration available")
        from app.subscription.wireguard import public_dial_host

        client_cfg = build_xray_native_client_config(
            private_key=settings["private_key"],
            local_address=local_address.split("/")[0] + "/32",
            server_public_key=cfg.public_key,
            server_host=public_dial_host(dbnode) or dbnode.address,
            server_port=finalmask_client_port(cfg, settings),
            preshared_key=settings.get("preshared_key"),
            mtu=finalmask_client_mtu(cfg, dbnode=dbnode, db=db),
            noise=cfg.xray_wg_noise,
        )
        filename = f"{dbuser.username}-{dbnode.name}-xray-wg.json"
        return Response(
            content=json.dumps(client_cfg, indent=2),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                **NO_STORE_HEADERS,
            },
        )

    conf = build_wireguard_user_config(settings, dbnode, variant=variant)
    if conf is None:
        raise HTTPException(status_code=404, detail="No WireGuard configuration available")

    suffix = {"awg": "-awg", "direct": "-direct"}.get(variant, "")
    filename = f"{dbuser.username}-{dbnode.name}{suffix}.conf"
    return Response(
        content=conf,
        media_type="text/plain",
        headers={
            "content-disposition": f'attachment; filename="{filename}"',
            **NO_STORE_HEADERS,
        },
    )


@router.get("/{token}/hysteria2")
@router.get("/{token}/hysteria2/{node_id}", include_in_schema=False)
def user_subscription_hysteria2(
    request: Request,
    dbuser=Depends(get_validated_sub),
    node_id: int = None,
    db: Session = Depends(get_db),
):
    """Return a ``hysteria2://`` share link for the user."""
    ensure_subscription_config_allowed(dbuser)
    _enforce_export_guards(db, dbuser, request)
    settings = _proxy_settings(dbuser, ProxyTypes.Hysteria2)
    if not settings:
        raise HTTPException(status_code=404, detail="No Hysteria2 configuration for this user")

    nodes = [
        n for n in crud.get_singbox_nodes(db)
        if n.singbox and n.singbox.hysteria2_enabled
    ]
    if node_id is not None:
        nodes = [n for n in nodes if n.id == node_id]
    if not nodes:
        raise HTTPException(status_code=404, detail="No Hysteria2 node available")

    n = pick_node(nodes, node_id)
    if not n:
        raise HTTPException(status_code=404, detail="No Hysteria2 node available")

    from app.subscription.region_display import node_config_remark

    link = user_hysteria2_link(
        settings, n, remark=node_config_remark(n, "Hysteria2"),
        speed_limit_up=dbuser.speed_limit_up,
        speed_limit_down=dbuser.speed_limit_down,
    )
    if not link:
        raise HTTPException(status_code=404, detail="No Hysteria2 configuration available")
    return Response(content=link + "\n", media_type="text/plain", headers=NO_STORE_HEADERS)


@router.get("/{token}/tuic")
@router.get("/{token}/tuic/{node_id}", include_in_schema=False)
def user_subscription_tuic(
    request: Request,
    dbuser=Depends(get_validated_sub),
    node_id: int = None,
    db: Session = Depends(get_db),
):
    """Return a ``tuic://`` share link for the user."""
    ensure_subscription_config_allowed(dbuser)
    _enforce_export_guards(db, dbuser, request)
    settings = _proxy_settings(dbuser, ProxyTypes.TUIC)
    if not settings:
        raise HTTPException(status_code=404, detail="No TUIC configuration for this user")

    nodes = [
        n for n in crud.get_singbox_nodes(db)
        if n.singbox and n.singbox.tuic_enabled
    ]
    if node_id is not None:
        nodes = [n for n in nodes if n.id == node_id]
    if not nodes:
        raise HTTPException(status_code=404, detail="No TUIC node available")

    n = pick_node(nodes, node_id)
    if not n:
        raise HTTPException(status_code=404, detail="No TUIC node available")

    from app.subscription.region_display import node_config_remark

    link = user_tuic_link(
        settings, n, remark=node_config_remark(n, "TUIC"),
        speed_limit_up=dbuser.speed_limit_up,
        speed_limit_down=dbuser.speed_limit_down,
    )
    if not link:
        raise HTTPException(status_code=404, detail="No TUIC configuration available")
    return Response(content=link + "\n", media_type="text/plain", headers=NO_STORE_HEADERS)


@router.get("/{token}/anytls")
@router.get("/{token}/anytls/{node_id}", include_in_schema=False)
def user_subscription_anytls(
    request: Request,
    dbuser=Depends(get_validated_sub),
    node_id: int = None,
    db: Session = Depends(get_db),
):
    """Return an ``anytls://`` share link for the user."""
    ensure_subscription_config_allowed(dbuser)
    _enforce_export_guards(db, dbuser, request)
    settings = _proxy_settings(dbuser, ProxyTypes.AnyTLS)
    if not settings:
        raise HTTPException(status_code=404, detail="No AnyTLS configuration for this user")

    nodes = [
        n for n in crud.get_singbox_nodes(db)
        if n.singbox and n.singbox.anytls_enabled
    ]
    if node_id is not None:
        nodes = [n for n in nodes if n.id == node_id]
    if not nodes:
        raise HTTPException(status_code=404, detail="No AnyTLS node available")

    n = pick_node(nodes, node_id)
    if not n:
        raise HTTPException(status_code=404, detail="No AnyTLS node available")

    from app.subscription.region_display import node_config_remark

    link = user_anytls_link(
        settings, n, remark=node_config_remark(n, "AnyTLS"),
        speed_limit_up=dbuser.speed_limit_up,
        speed_limit_down=dbuser.speed_limit_down,
    )
    if not link:
        raise HTTPException(status_code=404, detail="No AnyTLS configuration available")
    return Response(content=link + "\n", media_type="text/plain", headers=NO_STORE_HEADERS)


@router.get("/{token}/{client_type}")
def user_subscription_with_client_type(
    request: Request,
    dbuser: User = Depends(get_validated_sub),
    sub_ctx: SubscriptionRequestContext = Depends(get_subscription_context),
    client_type: str = Path(..., regex="sing-box|clash-meta|clash|outline|v2ray|v2ray-json|surge|loon|quantumult"),
    db: Session = Depends(get_db),
    user_agent: str = Header(default="")
):
    """Provides a subscription link based on the specified client type (e.g., Clash, V2Ray)."""
    sub_ctx = resolve_sub_ctx(sub_ctx, request, db)
    user: UserResponse = UserResponse.model_validate(dbuser, context={"skip_default_links": True})
    access = subscription_access(user)
    if access["config_available"]:
        ensure_subscription_config_allowed(user)
        _enforce_export_guards(db, dbuser, request)

    req_token = request.path_params.get("token", "")
    response_headers = _subscription_response_headers(
        user, request, req_token, endpoint=sub_ctx.endpoint
    )
    if not access["config_available"]:
        response_headers["profile-title"] = encode_title(blocked_message(access["block_reason"]))

    config = client_config.get(client_type)
    if not config:
        raise HTTPException(status_code=404, detail=f"Unknown client type: {client_type}")
    conf, _ = _resolve_subscription_body(
        user,
        config_format=config["config_format"],
        as_base64=config["as_base64"],
        reverse=config["reverse"],
        inbound_filter=sub_ctx.inbound_filter,
        profile_web_page_url=response_headers.get("profile-web-page-url", ""),
    )

    return Response(content=conf, media_type=config["media_type"], headers=response_headers)
