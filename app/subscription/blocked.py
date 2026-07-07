"""Subscription placeholders shown inside VPN clients when quota/time blocks export."""

from __future__ import annotations

import base64
import json
from typing import Literal
from urllib.parse import quote

import yaml

from app.subscription.guards import BlockReason
from config import (
    SUB_BLOCKED_DATA_LIMIT_MESSAGE,
    SUB_BLOCKED_EXPIRED_MESSAGE,
    SUB_BLOCKED_INACTIVE_MESSAGE,
)

ConfigFormat = Literal[
    "v2ray",
    "clash-meta",
    "clash",
    "sing-box",
    "outline",
    "v2ray-json",
    "surge",
    "loon",
    "quantumult",
]

_PLACEHOLDER_HOST = "127.0.0.1"
_PLACEHOLDER_PORT = 1
_PLACEHOLDER_CIPHER = "aes-256-gcm"
_PLACEHOLDER_PASSWORD = "blocked"


def blocked_message(block_reason: BlockReason | None) -> str:
    if block_reason == "data_limit":
        return SUB_BLOCKED_DATA_LIMIT_MESSAGE
    if block_reason == "expired":
        return SUB_BLOCKED_EXPIRED_MESSAGE
    return SUB_BLOCKED_INACTIVE_MESSAGE


def _safe_proxy_name(message: str) -> str:
    return message.replace(",", "،").replace("\n", " ").strip() or "Subscription inactive"


def blocked_v2ray_share_link(block_reason: BlockReason | None) -> str:
    """Single ss:// line — remark (fragment) is the user-visible message."""
    message = _safe_proxy_name(blocked_message(block_reason))
    cred = base64.urlsafe_b64encode(
        f"{_PLACEHOLDER_CIPHER}:{_PLACEHOLDER_PASSWORD}".encode()
    ).decode().rstrip("=")
    return f"ss://{cred}@{_PLACEHOLDER_HOST}:{_PLACEHOLDER_PORT}#{quote(message)}"


def _blocked_v2ray_json(block_reason: BlockReason | None) -> str:
    message = _safe_proxy_name(blocked_message(block_reason))
    entry = {
        "remarks": message,
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "tag": "socks",
                "port": 10808,
                "listen": "127.0.0.1",
                "protocol": "socks",
                "settings": {"auth": "noauth", "udp": True},
            }
        ],
        "outbounds": [
            {
                "tag": "proxy",
                "protocol": "shadowsocks",
                "settings": {
                    "servers": [
                        {
                            "address": _PLACEHOLDER_HOST,
                            "port": _PLACEHOLDER_PORT,
                            "method": _PLACEHOLDER_CIPHER,
                            "password": _PLACEHOLDER_PASSWORD,
                        }
                    ]
                },
            },
            {"tag": "direct", "protocol": "freedom"},
            {"tag": "block", "protocol": "blackhole"},
        ],
        "routing": {"domainStrategy": "AsIs", "rules": []},
    }
    return json.dumps([entry], indent=2)


def _blocked_clash_yaml(block_reason: BlockReason | None, *, meta: bool) -> str:
    message = _safe_proxy_name(blocked_message(block_reason))
    doc = {
        "mixed-port": 7890,
        "mode": "Rule",
        "log-level": "info",
        "proxies": [
            {
                "name": message,
                "type": "ss",
                "server": _PLACEHOLDER_HOST,
                "port": _PLACEHOLDER_PORT,
                "cipher": _PLACEHOLDER_CIPHER,
                "password": _PLACEHOLDER_PASSWORD,
                "udp": True,
            }
        ],
        "proxy-groups": [
            {
                "name": "Proxy",
                "type": "select",
                "proxies": [message],
            }
        ],
        "rules": ["MATCH,Proxy"],
    }
    if meta:
        doc["unified-delay"] = True
    return yaml.dump(doc, allow_unicode=True, sort_keys=False)


def _blocked_singbox(block_reason: BlockReason | None) -> str:
    message = _safe_proxy_name(blocked_message(block_reason))
    tag = message[:64]
    doc = {
        "log": {"level": "info"},
        "outbounds": [
            {"type": "direct", "tag": "direct"},
            {"type": "block", "tag": "block"},
            {
                "type": "shadowsocks",
                "tag": tag,
                "server": _PLACEHOLDER_HOST,
                "server_port": _PLACEHOLDER_PORT,
                "method": _PLACEHOLDER_CIPHER,
                "password": _PLACEHOLDER_PASSWORD,
            },
            {
                "type": "selector",
                "tag": "select",
                "outbounds": [tag],
                "default": tag,
            },
        ],
    }
    return json.dumps(doc, indent=2, ensure_ascii=False)


def _blocked_outline(block_reason: BlockReason | None) -> str:
    message = _safe_proxy_name(blocked_message(block_reason))
    return json.dumps(
        {
            message: {
                "method": _PLACEHOLDER_CIPHER,
                "password": _PLACEHOLDER_PASSWORD,
                "server": _PLACEHOLDER_HOST,
                "server_port": _PLACEHOLDER_PORT,
                "tag": message,
            }
        },
        indent=2,
    )


def _blocked_surge_line(block_reason: BlockReason | None) -> str:
    message = _safe_proxy_name(blocked_message(block_reason))
    safe = message.replace(",", "，")
    return (
        f"{safe} = ss, {_PLACEHOLDER_HOST}, {_PLACEHOLDER_PORT}, "
        f"{_PLACEHOLDER_CIPHER}, {_PLACEHOLDER_PASSWORD}, tfo=true"
    )


def _blocked_surge(block_reason: BlockReason | None) -> str:
    line = _blocked_surge_line(block_reason)
    return f"#!MANAGED-CONFIG interval=86400\n\n[Proxy]\n{line}\n"


def _blocked_loon(block_reason: BlockReason | None) -> str:
    line = _blocked_surge_line(block_reason)
    return f"[Proxy]\n{line}\n"


def _blocked_quantumult(block_reason: BlockReason | None) -> str:
    """Quantumult X reads vmess:// lines; ps field is the visible name."""
    message = _safe_proxy_name(blocked_message(block_reason))
    payload = base64.b64encode(
        json.dumps(
            {
                "v": "2",
                "ps": message,
                "add": _PLACEHOLDER_HOST,
                "port": str(_PLACEHOLDER_PORT),
                "id": "00000000-0000-0000-0000-000000000000",
                "aid": "0",
                "net": "tcp",
                "type": "none",
                "host": "",
                "path": "",
                "tls": "",
            },
            separators=(",", ":"),
        ).encode()
    ).decode()
    return f"vmess://{payload}\n"


def generate_blocked_subscription(
    *,
    block_reason: BlockReason | None,
    config_format: ConfigFormat,
    as_base64: bool = False,
    reverse: bool = False,
) -> str:
    """Build a valid client subscription body with a non-working message placeholder."""
    builders = {
        "v2ray": lambda: blocked_v2ray_share_link(block_reason),
        "v2ray-json": lambda: _blocked_v2ray_json(block_reason),
        "clash-meta": lambda: _blocked_clash_yaml(block_reason, meta=True),
        "clash": lambda: _blocked_clash_yaml(block_reason, meta=False),
        "sing-box": lambda: _blocked_singbox(block_reason),
        "outline": lambda: _blocked_outline(block_reason),
        "surge": lambda: _blocked_surge(block_reason),
        "loon": lambda: _blocked_loon(block_reason),
        "quantumult": lambda: _blocked_quantumult(block_reason),
    }
    conf = builders[config_format]()
    if reverse and config_format == "v2ray":
        pass  # single placeholder line
    if as_base64:
        conf = base64.b64encode(conf.encode()).decode()
    return conf
