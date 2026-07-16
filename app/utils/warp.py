"""Cloudflare WARP integration.

Generates WireGuard credentials locally and registers a free WARP device with
Cloudflare's client API (mirroring 3x-ui's WarpService). The registered account
yields a working WireGuard outbound (secretKey, addresses, peer publicKey,
endpoint and reserved bytes) that Xray can use to tunnel traffic through WARP.
"""

from __future__ import annotations

import base64
import json
import os
import socket
from datetime import datetime, timezone
from typing import Optional

import requests
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from config import WARP_DATA

WARP_API_BASE = "https://api.cloudflareclient.com/v0a2158"
CF_CLIENT_VERSION = "a-7.21-0721"
DEFAULT_ENDPOINT = "engage.cloudflareclient.com:2408"
DEFAULT_PEER_PUBLIC_KEY = "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo="


class WarpError(Exception):
    """Raised when a Cloudflare WARP API interaction fails."""


def generate_wireguard_keys() -> tuple[str, str]:
    """Return a (private_key, public_key) base64 pair compatible with `wg`."""
    private = bytearray(os.urandom(32))
    # WireGuard key clamping.
    private[0] &= 248
    private[31] &= 127
    private[31] |= 64
    priv_obj = X25519PrivateKey.from_private_bytes(bytes(private))
    public = priv_obj.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return (
        base64.b64encode(bytes(private)).decode(),
        base64.b64encode(public).decode(),
    )


def _headers(token: Optional[str] = None) -> dict:
    headers = {
        "Content-Type": "application/json",
        "CF-Client-Version": CF_CLIENT_VERSION,
        "User-Agent": "okhttp/3.12.1",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _reserved_from_client_id(client_id: str) -> list[int]:
    try:
        raw = base64.b64decode(client_id)
    except Exception:
        return [0, 0, 0]
    # WireGuard's "reserved" field is always exactly 3 bytes; a missing or
    # short client_id must fall back to the zeroed default rather than
    # silently emitting a malformed (shorter) array that would break the
    # handshake.
    if len(raw) < 3:
        return [0, 0, 0]
    return list(raw[:3])


def _build_outbound(account: dict, tag: str = "warp") -> dict:
    cfg = account.get("config", {})
    interface = cfg.get("interface", {})
    addresses_obj = interface.get("addresses", {}) if isinstance(interface, dict) else {}
    addresses: list[str] = []
    v4 = addresses_obj.get("v4")
    v6 = addresses_obj.get("v6")
    if v4:
        addresses.append(f"{v4}/32")
    if v6:
        addresses.append(f"{v6}/128")
    if not addresses:
        addresses = ["172.16.0.2/32"]

    peers = cfg.get("peers") or []
    peer_public = DEFAULT_PEER_PUBLIC_KEY
    endpoint = DEFAULT_ENDPOINT
    if peers and isinstance(peers[0], dict):
        peer_public = peers[0].get("public_key") or peer_public
        ep = peers[0].get("endpoint")
        if isinstance(ep, dict):
            endpoint = ep.get("host") or endpoint
        elif isinstance(ep, str):
            endpoint = ep

    reserved = _reserved_from_client_id(cfg.get("client_id", ""))

    from app.xray.warp_routing import resolve_warp_endpoint_ip

    endpoint_ip = resolve_warp_endpoint_ip()
    peer_endpoint = f"{endpoint_ip}:{DEFAULT_ENDPOINT.rsplit(':', 1)[-1]}" if endpoint_ip else endpoint

    return {
        "tag": tag,
        "protocol": "wireguard",
        "settings": {
            "secretKey": account["private_key"],
            "address": addresses,
            "peers": [
                {
                    "publicKey": peer_public,
                    "endpoint": peer_endpoint,
                    "allowedIPs": ["0.0.0.0/0", "::/0"],
                }
            ],
            "reserved": reserved,
            "mtu": 1280,
            "workers": 4,
            "noKernelTun": True,
        },
    }


def load_warp_data() -> Optional[dict]:
    """Return the persisted WARP store, or None if not registered."""
    if not os.path.exists(WARP_DATA):
        return None
    try:
        with open(WARP_DATA, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _normalize_store(raw: Optional[dict]) -> dict:
    if not raw:
        return {"accounts": {}, "default": None}
    if isinstance(raw.get("accounts"), dict):
        return raw
    tag = str(raw.get("tag") or "warp")
    return {"accounts": {tag: raw}, "default": tag}


def _account_from_store(store: dict, tag: Optional[str] = None) -> Optional[dict]:
    accounts = store.get("accounts") or {}
    if not accounts:
        return None
    key = tag or store.get("default") or next(iter(accounts))
    return accounts.get(key)


def save_warp_data(data: dict) -> None:
    with open(WARP_DATA, "w") as f:
        json.dump(data, f, indent=2)


def save_warp_account(tag: str, account: dict) -> None:
    store = _normalize_store(load_warp_data())
    store.setdefault("accounts", {})[tag] = account
    if not store.get("default"):
        store["default"] = tag
    save_warp_data(store)


def delete_warp_data(tag: Optional[str] = None) -> None:
    if tag:
        store = _normalize_store(load_warp_data())
        accounts = store.get("accounts") or {}
        accounts.pop(tag, None)
        if store.get("default") == tag:
            store["default"] = next(iter(accounts), None)
        store["accounts"] = accounts
        if accounts:
            save_warp_data(store)
        elif os.path.exists(WARP_DATA):
            os.remove(WARP_DATA)
        return
    if os.path.exists(WARP_DATA):
        os.remove(WARP_DATA)


def list_warp_accounts() -> dict:
    store = _normalize_store(load_warp_data())
    accounts = store.get("accounts") or {}
    return {
        "default": store.get("default"),
        "accounts": {
            tag: _sanitize(acct, tag=tag)
            for tag, acct in accounts.items()
        },
    }


def _sanitize(account: dict, tag: str = "warp") -> dict:
    """Public view of the account (no secretKey leakage beyond the outbound)."""
    cfg = account.get("config", {})
    cf_account = cfg.get("account", {}) if isinstance(cfg, dict) else {}
    is_plus = bool(cf_account.get("warp_plus"))
    # Cloudflare's client API reports account_type "free" for every personal
    # device regardless of Plus status; `warp_plus` is the real signal for a
    # license/referral upgrade, so it must win over the literal "free" string.
    account_type = "plus" if is_plus else (cf_account.get("account_type") or "free")
    return {
        "tag": tag,
        "device_id": account.get("device_id"),
        "license_key": account.get("license_key"),
        "account_type": account_type,
        "warp_plus": is_plus,
        "premium_data": cf_account.get("premium_data"),
        "quota": cf_account.get("quota"),
        "registered": True,
        "outbound": _build_outbound(account, tag=tag),
    }


def register_warp(tag: str = "warp") -> dict:
    """Register a fresh WARP device and persist credentials.

    Returns a dict with the public account view and a ready-to-use Xray
    wireguard outbound.
    """
    private_key, public_key = generate_wireguard_keys()
    tos = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    try:
        hostname = socket.gethostname() or "nexuspanel"
    except Exception:
        hostname = "nexuspanel"

    try:
        resp = requests.post(
            f"{WARP_API_BASE}/reg",
            data=json.dumps(
                {
                    "key": public_key,
                    "tos": tos,
                    "type": "PC",
                    "model": "NexusPanel",
                    "name": hostname,
                    "locale": "en_US",
                }
            ),
            headers=_headers(),
            timeout=30,
        )
    except requests.RequestException as err:
        raise WarpError(f"Could not reach Cloudflare WARP API: {err}")

    if resp.status_code >= 400:
        raise WarpError(f"WARP registration failed ({resp.status_code}): {resp.text[:200]}")

    try:
        data = resp.json()
    except ValueError:
        raise WarpError("WARP API returned an invalid response")

    try:
        device_id = data["id"]
        token = data["token"]
        cf_account = data.get("account", {})
        license_key = cf_account.get("license", "")
    except (KeyError, TypeError):
        raise WarpError("WARP API response missing required fields")

    account = {
        "device_id": device_id,
        "access_token": token,
        "license_key": license_key,
        "private_key": private_key,
        "public_key": public_key,
        "config": data.get("config", {}),
        "account": cf_account,
    }
    # keep account block inside config for outbound builder convenience
    if isinstance(account["config"], dict):
        account["config"].setdefault("account", cf_account)

    save_warp_account(tag, account)
    return _sanitize(account, tag=tag)


def get_warp(tag: Optional[str] = None) -> Optional[dict]:
    store = _normalize_store(load_warp_data())
    account = _account_from_store(store, tag)
    if not account:
        return None
    resolved = tag or store.get("default") or "warp"
    return _sanitize(account, tag=resolved)


def set_warp_license(license_key: str, tag: Optional[str] = None) -> dict:
    """Apply a WARP+ license key to the registered device."""
    store = _normalize_store(load_warp_data())
    resolved = tag or store.get("default") or "warp"
    account = _account_from_store(store, resolved)
    if not account:
        raise WarpError("No WARP device registered yet")

    try:
        resp = requests.put(
            f"{WARP_API_BASE}/reg/{account['device_id']}/account",
            data=json.dumps({"license": license_key}),
            headers=_headers(account["access_token"]),
            timeout=30,
        )
    except requests.RequestException as err:
        raise WarpError(f"Could not reach Cloudflare WARP API: {err}")

    if resp.status_code >= 400:
        raise WarpError(f"License update failed ({resp.status_code}): {resp.text[:200]}")

    try:
        body = resp.json()
    except ValueError:
        body = {}

    if body.get("success") is False:
        errors = body.get("errors") or [{}]
        msg = errors[0].get("message", "license rejected")
        raise WarpError(f"Cloudflare rejected license: {msg}")

    account["license_key"] = license_key
    if isinstance(body, dict) and body:
        account["account"] = body
        if isinstance(account.get("config"), dict):
            account["config"]["account"] = body
    save_warp_account(resolved, account)
    return _sanitize(account, tag=resolved)
