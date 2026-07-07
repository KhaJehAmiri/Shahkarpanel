"""OIDC authorization-code flow helpers for admin SSO."""
from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlencode

import requests

from config import (
    OIDC_CLIENT_ID,
    OIDC_CLIENT_SECRET,
    OIDC_ISSUER,
    OIDC_REDIRECT_URI,
    OIDC_USERNAME_CLAIM,
)


class OidcError(Exception):
    pass


def oidc_enabled() -> bool:
    return bool(OIDC_ISSUER and OIDC_CLIENT_ID and OIDC_CLIENT_SECRET and OIDC_REDIRECT_URI)


def authorize_url(state: str = "") -> str:
    if not oidc_enabled():
        raise OidcError("OIDC is not configured")
    base = OIDC_ISSUER.rstrip("/")
    params = {
        "client_id": OIDC_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": OIDC_REDIRECT_URI,
        "scope": "openid email profile",
    }
    if state:
        params["state"] = state
    return f"{base}/authorize?{urlencode(params)}"


def exchange_code(code: str, redirect_uri: Optional[str] = None) -> dict[str, Any]:
    if not oidc_enabled():
        raise OidcError("OIDC is not configured")
    token_url = f"{OIDC_ISSUER.rstrip('/')}/token"
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri or OIDC_REDIRECT_URI,
        "client_id": OIDC_CLIENT_ID,
        "client_secret": OIDC_CLIENT_SECRET,
    }
    try:
        resp = requests.post(token_url, data=data, timeout=30)
    except requests.RequestException as err:
        raise OidcError(f"Token endpoint unreachable: {err}") from err
    if resp.status_code >= 400:
        raise OidcError(f"Token exchange failed ({resp.status_code})")
    try:
        payload = resp.json()
    except ValueError as err:
        raise OidcError("Invalid token response") from err
    if not payload.get("access_token"):
        raise OidcError("Token response missing access_token")
    return payload


def fetch_userinfo(access_token: str) -> dict[str, Any]:
    url = f"{OIDC_ISSUER.rstrip('/')}/userinfo"
    try:
        resp = requests.get(url, headers={"Authorization": f"Bearer {access_token}"}, timeout=30)
    except requests.RequestException as err:
        raise OidcError(f"Userinfo unreachable: {err}") from err
    if resp.status_code >= 400:
        raise OidcError(f"Userinfo failed ({resp.status_code})")
    try:
        return resp.json()
    except ValueError as err:
        raise OidcError("Invalid userinfo response") from err


def username_from_claims(claims: dict[str, Any]) -> str:
    claim = (OIDC_USERNAME_CLAIM or "preferred_username").strip()
    for key in (claim, "preferred_username", "email", "sub"):
        val = claims.get(key)
        if val:
            text = str(val).strip()
            if key == "email" and "@" in text:
                return text.split("@", 1)[0]
            return text
    raise OidcError("No username claim in userinfo")
