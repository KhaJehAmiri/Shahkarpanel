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
        return [b for b in raw[:3]]
    except Exception:
        return [0, 0, 0]


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

    return {
        "tag": tag,
        "protocol": "wireguard",
        "settings": {
            "secretKey": account["private_key"],
            "address": addresses,
            "peers": [
                {
                    "publicKey": peer_public,
                    "endpoint": endpoint,
                    "allowedIPs": ["0.0.0.0/0", "::/0"],
                }
            ],
            "reserved": reserved,
            "mtu": 1280,
            "workers": 2,
        },
    }


def load_warp_data() -> Optional[dict]:
    """Return the persisted WARP account, or None if not registered."""
    if not os.path.exists(WARP_DATA):
        return None
    try:
        with open(WARP_DATA, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save_warp_data(data: dict) -> None:
    with open(WARP_DATA, "w") as f:
        json.dump(data, f, indent=2)


def delete_warp_data() -> None:
    if os.path.exists(WARP_DATA):
        os.remove(WARP_DATA)


def _sanitize(account: dict) -> dict:
    """Public view of the account (no secretKey leakage beyond the outbound)."""
    cfg = account.get("config", {})
    cf_account = cfg.get("account", {}) if isinstance(cfg, dict) else {}
    return {
        "device_id": account.get("device_id"),
        "license_key": account.get("license_key"),
        "account_type": cf_account.get("account_type") or cf_account.get("warp_plus") and "warp_plus" or "free",
        "premium_data": cf_account.get("premium_data"),
        "quota": cf_account.get("quota"),
        "registered": True,
        "outbound": _build_outbound(account),
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

    save_warp_data(account)
    return _sanitize(account)


def get_warp() -> Optional[dict]:
    account = load_warp_data()
    if not account:
        return None
    return _sanitize(account)


def set_warp_license(license_key: str) -> dict:
    """Apply a WARP+ license key to the registered device."""
    account = load_warp_data()
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
    save_warp_data(account)
    return _sanitize(account)
