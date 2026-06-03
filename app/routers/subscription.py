import re
from distutils.version import LooseVersion
from pathlib import Path as _Path

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db import Session, crud, get_db
from app.dependencies import get_validated_sub, validate_dates
from app.models.proxy import ProxyTypes
from app.models.user import SubscriptionUserResponse, UserResponse, UserStatus
from app.subscription.share import encode_title, generate_subscription
from app.subscription.wireguard import user_config as build_wireguard_user_config
from app.templates import render_template
from config import (
    SUB_PROFILE_TITLE,
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
                   "reverse": False}
}

router = APIRouter(tags=['Subscription'], prefix=f'/{XRAY_SUBSCRIPTION_PATH}')


def get_subscription_user_info(user: UserResponse) -> dict:
    """Retrieve user subscription information including upload, download, total data, and expiry."""
    return {
        "upload": 0,
        "download": user.used_traffic,
        "total": user.data_limit if user.data_limit is not None else 0,
        "expire": user.expire if user.expire is not None else 0,
    }


@router.get("/{token}/")
@router.get("/{token}", include_in_schema=False)
def user_subscription(
    request: Request,
    db: Session = Depends(get_db),
    dbuser: UserResponse = Depends(get_validated_sub),
    user_agent: str = Header(default="")
):
    """Provides a subscription link based on the user agent (Clash, V2Ray, etc.)."""
    user: UserResponse = UserResponse.model_validate(dbuser)

    accept_header = request.headers.get("Accept", "")
    if "text/html" in accept_header:
        # Phase 9: prefer the new Next.js subscription page (graphical, with
        # platform tabs) when its static build is present. The page reads the
        # token from the URL and fetches /sub/<token>/info itself.
        next_index = _Path(__file__).parent.parent / 'dashboard-next' / 'out' / 'subscribe' / 'index.html'
        if next_index.is_file():
            token = request.path_params.get('token', '')
            return RedirectResponse(
                url=f"/subscribe/?token={token}",
                status_code=302,
            )
        return HTMLResponse(
            render_template(
                SUBSCRIPTION_PAGE_TEMPLATE,
                {"user": user}
            )
        )

    crud.update_user_sub(db, dbuser, user_agent)
    response_headers = {
        "content-disposition": f'attachment; filename="{user.username}"',
        "profile-web-page-url": str(request.url),
        "support-url": SUB_SUPPORT_URL,
        "profile-title": encode_title(SUB_PROFILE_TITLE),
        "profile-update-interval": SUB_UPDATE_INTERVAL,
        "subscription-userinfo": "; ".join(
            f"{key}={val}"
            for key, val in get_subscription_user_info(user).items()
        )
    }

    if re.match(r'^([Cc]lash-verge|[Cc]lash[-\.]?[Mm]eta|[Ff][Ll][Cc]lash|[Mm]ihomo)', user_agent):
        conf = generate_subscription(user=user, config_format="clash-meta", as_base64=False, reverse=False)
        return Response(content=conf, media_type="text/yaml", headers=response_headers)

    elif re.match(r'^([Cc]lash|[Ss]tash)', user_agent):
        conf = generate_subscription(user=user, config_format="clash", as_base64=False, reverse=False)
        return Response(content=conf, media_type="text/yaml", headers=response_headers)

    elif re.match(r'^(SFA|SFI|SFM|SFT|[Kk]aring|[Hh]iddify[Nn]ext)', user_agent):
        conf = generate_subscription(user=user, config_format="sing-box", as_base64=False, reverse=False)
        return Response(content=conf, media_type="application/json", headers=response_headers)

    elif re.match(r'^(SS|SSR|SSD|SSS|Outline|Shadowsocks|SSconf)', user_agent):
        conf = generate_subscription(user=user, config_format="outline", as_base64=False, reverse=False)
        return Response(content=conf, media_type="application/json", headers=response_headers)

    elif (USE_CUSTOM_JSON_DEFAULT or USE_CUSTOM_JSON_FOR_V2RAYN) and re.match(r'^v2rayN/(\d+\.\d+)', user_agent):
        version_str = re.match(r'^v2rayN/(\d+\.\d+)', user_agent).group(1)
        if LooseVersion(version_str) >= LooseVersion("6.40"):
            conf = generate_subscription(user=user, config_format="v2ray-json", as_base64=False, reverse=False)
            return Response(content=conf, media_type="application/json", headers=response_headers)
        else:
            conf = generate_subscription(user=user, config_format="v2ray", as_base64=True, reverse=False)
            return Response(content=conf, media_type="text/plain", headers=response_headers)

    elif (USE_CUSTOM_JSON_DEFAULT or USE_CUSTOM_JSON_FOR_V2RAYNG) and re.match(r'^v2rayNG/(\d+\.\d+\.\d+)', user_agent):
        version_str = re.match(r'^v2rayNG/(\d+\.\d+\.\d+)', user_agent).group(1)
        if LooseVersion(version_str) >= LooseVersion("1.8.29"):
            conf = generate_subscription(user=user, config_format="v2ray-json", as_base64=False, reverse=False)
            return Response(content=conf, media_type="application/json", headers=response_headers)
        elif LooseVersion(version_str) >= LooseVersion("1.8.18"):
            conf = generate_subscription(user=user, config_format="v2ray-json", as_base64=False, reverse=True)
            return Response(content=conf, media_type="application/json", headers=response_headers)
        else:
            conf = generate_subscription(user=user, config_format="v2ray", as_base64=True, reverse=False)
            return Response(content=conf, media_type="text/plain", headers=response_headers)

    elif re.match(r'^[Ss]treisand', user_agent):
        if USE_CUSTOM_JSON_DEFAULT or USE_CUSTOM_JSON_FOR_STREISAND:
            conf = generate_subscription(user=user, config_format="v2ray-json", as_base64=False, reverse=False)
            return Response(content=conf, media_type="application/json", headers=response_headers)
        else:
            conf = generate_subscription(user=user, config_format="v2ray", as_base64=True, reverse=False)
            return Response(content=conf, media_type="text/plain", headers=response_headers)

    elif (USE_CUSTOM_JSON_DEFAULT or USE_CUSTOM_JSON_FOR_HAPP) and re.match(r'^Happ/(\d+\.\d+\.\d+)', user_agent):
        version_str = re.match(r'^Happ/(\d+\.\d+\.\d+)', user_agent).group(1)
        if LooseVersion(version_str) >= LooseVersion("1.63.1"):
            conf = generate_subscription(user=user, config_format="v2ray-json", as_base64=False, reverse=False)
            return Response(content=conf, media_type="application/json", headers=response_headers)
        else:
            conf = generate_subscription(user=user, config_format="v2ray", as_base64=True, reverse=False)
            return Response(content=conf, media_type="text/plain", headers=response_headers)



    else:
        conf = generate_subscription(user=user, config_format="v2ray", as_base64=True, reverse=False)
        return Response(content=conf, media_type="text/plain", headers=response_headers)


@router.get("/{token}/info", response_model=SubscriptionUserResponse)
def user_subscription_info(
    dbuser: UserResponse = Depends(get_validated_sub),
):
    """Retrieves detailed information about the user's subscription."""
    return dbuser


@router.get("/{token}/usage")
def user_get_usage(
    dbuser: UserResponse = Depends(get_validated_sub),
    start: str = "",
    end: str = "",
    db: Session = Depends(get_db)
):
    """Fetches the usage statistics for the user within a specified date range."""
    start, end = validate_dates(start, end)

    usages = crud.get_user_usages(db, dbuser, start, end)

    return {"usages": usages, "username": dbuser.username}


def _wireguard_user_settings(dbuser) -> dict:
    """Return the user's WireGuard proxy settings dict, or ``None``."""
    for proxy in dbuser.proxies:
        if proxy.type is ProxyTypes.WireGuard:
            return proxy.settings or {}
    return None


@router.get("/{token}/wireguard")
@router.get("/{token}/wireguard/{node_id}", include_in_schema=False)
def user_subscription_wireguard(
    dbuser=Depends(get_validated_sub),
    node_id: int = None,
    db: Session = Depends(get_db),
):
    """Return a wg-quick ``.conf`` for the user, tied to the same token and
    central quota. Issuance is gated on billable status / quota so a
    disabled / limited / expired user does not receive a working config."""
    if dbuser.status not in (UserStatus.active, UserStatus.on_hold):
        raise HTTPException(status_code=403, detail="Subscription is not active")
    if dbuser.data_limit and dbuser.used_traffic >= dbuser.data_limit:
        raise HTTPException(status_code=403, detail="Data limit reached")

    settings = _wireguard_user_settings(dbuser)
    if not settings:
        raise HTTPException(status_code=404, detail="No WireGuard configuration for this user")

    nodes = [n for n in crud.get_wireguard_nodes(db) if n.wireguard is not None]
    if node_id is not None:
        nodes = [n for n in nodes if n.id == node_id]
    if not nodes:
        raise HTTPException(status_code=404, detail="No WireGuard node available")

    dbnode = nodes[0]

    # Lazily allocate a peer IP from the node subnet if the user has none yet,
    # so the .conf is usable even before the node has synced.
    if not settings.get("address"):
        from app.wireguard.operations import ensure_user_address
        for proxy in dbuser.proxies:
            if proxy.type is ProxyTypes.WireGuard:
                ensure_user_address(db, proxy, dbnode.wireguard.subnet)
                settings = proxy.settings or {}
                break

    conf = build_wireguard_user_config(settings, dbnode)
    if conf is None:
        raise HTTPException(status_code=404, detail="No WireGuard configuration available")

    filename = f"{dbuser.username}-{dbnode.name}.conf"
    return Response(
        content=conf,
        media_type="text/plain",
        headers={"content-disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{token}/{client_type}")
def user_subscription_with_client_type(
    request: Request,
    dbuser: UserResponse = Depends(get_validated_sub),
    client_type: str = Path(..., regex="sing-box|clash-meta|clash|outline|v2ray|v2ray-json"),
    db: Session = Depends(get_db),
    user_agent: str = Header(default="")
):
    """Provides a subscription link based on the specified client type (e.g., Clash, V2Ray)."""
    user: UserResponse = UserResponse.model_validate(dbuser)

    response_headers = {
        "content-disposition": f'attachment; filename="{user.username}"',
        "profile-web-page-url": str(request.url),
        "support-url": SUB_SUPPORT_URL,
        "profile-title": encode_title(SUB_PROFILE_TITLE),
        "profile-update-interval": SUB_UPDATE_INTERVAL,
        "subscription-userinfo": "; ".join(
            f"{key}={val}"
            for key, val in get_subscription_user_info(user).items()
        )
    }

    config = client_config.get(client_type)
    conf = generate_subscription(user=user,
                                 config_format=config["config_format"],
                                 as_base64=config["as_base64"],
                                 reverse=config["reverse"])

    return Response(content=conf, media_type=config["media_type"], headers=response_headers)
