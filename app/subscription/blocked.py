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
    SUB_BLOCKED_DEVICE_LIMIT_MESSAGE,
    SUB_BLOCKED_EXPIRED_MESSAGE,
    SUB_BLOCKED_FAMILY_SCHEDULE_MESSAGE,
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


def blocked_message(
    block_reason: BlockReason | None,
    *,
    override: str | None = None,
    minutes_left: int | None = None,
) -> str:
    if override:
        return override
    if block_reason == "data_limit":
        return SUB_BLOCKED_DATA_LIMIT_MESSAGE
    if block_reason == "expired":
        return SUB_BLOCKED_EXPIRED_MESSAGE
    if block_reason == "family_schedule":
        return SUB_BLOCKED_FAMILY_SCHEDULE_MESSAGE
    if block_reason == "device_limit":
        mins = int(minutes_left or 30)
        try:
            return SUB_BLOCKED_DEVICE_LIMIT_MESSAGE.format(minutes=mins)
        except Exception:
            return f"{SUB_BLOCKED_DEVICE_LIMIT_MESSAGE} ({mins} دقیقه)"
    return SUB_BLOCKED_INACTIVE_MESSAGE


def _safe_proxy_name(message: str) -> str:
    return message.replace(",", "،").replace("\n", " ").strip() or "Subscription inactive"


def generate_blocked_subscription(
    *,
    block_reason: BlockReason | None,
    config_format: ConfigFormat,
    as_base64: bool = False,
    reverse: bool = False,
    message_override: str | None = None,
    minutes_left: int | None = None,
) -> str:
    """Build a valid client subscription body with a non-working message placeholder."""
    message = _safe_proxy_name(
        blocked_message(
            block_reason,
            override=message_override,
            minutes_left=minutes_left,
        )
    )
    builders = {
        "v2ray": lambda: _blocked_v2ray_share_link_msg(message),
        "v2ray-json": lambda: _blocked_v2ray_json_msg(message),
        "clash-meta": lambda: _blocked_clash_yaml_msg(message, meta=True),
        "clash": lambda: _blocked_clash_yaml_msg(message, meta=False),
        "sing-box": lambda: _blocked_singbox_msg(message),
        "outline": lambda: _blocked_outline_msg(message),
        "surge": lambda: _blocked_surge_msg(message),
        "loon": lambda: _blocked_loon_msg(message),
        "quantumult": lambda: _blocked_quantumult_msg(message),
    }
    conf = builders[config_format]()
    if reverse and config_format == "v2ray":
        pass  # single placeholder line
    if as_base64:
        conf = base64.b64encode(conf.encode()).decode()
    return conf


def blocked_v2ray_share_link(block_reason: BlockReason | None) -> str:
    return _blocked_v2ray_share_link_msg(_safe_proxy_name(blocked_message(block_reason)))


def _blocked_v2ray_share_link_msg(message: str) -> str:
    """Single ss:// line — remark (fragment) is the user-visible message."""
    cred = base64.urlsafe_b64encode(
        f"{_PLACEHOLDER_CIPHER}:{_PLACEHOLDER_PASSWORD}".encode()
    ).decode().rstrip("=")
    return f"ss://{cred}@{_PLACEHOLDER_HOST}:{_PLACEHOLDER_PORT}#{quote(message)}"


def _blocked_v2ray_json(block_reason: BlockReason | None) -> str:
    return _blocked_v2ray_json_msg(_safe_proxy_name(blocked_message(block_reason)))


def _blocked_v2ray_json_msg(message: str) -> str:
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
    return _blocked_clash_yaml_msg(
        _safe_proxy_name(blocked_message(block_reason)), meta=meta
    )


def _blocked_clash_yaml_msg(message: str, *, meta: bool) -> str:
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
    return _blocked_singbox_msg(_safe_proxy_name(blocked_message(block_reason)))


def _blocked_singbox_msg(message: str) -> str:
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
    return _blocked_outline_msg(_safe_proxy_name(blocked_message(block_reason)))


def _blocked_outline_msg(message: str) -> str:
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


def _blocked_surge_line_msg(message: str) -> str:
    safe = message.replace(",", "，")
    return (
        f"{safe} = ss, {_PLACEHOLDER_HOST}, {_PLACEHOLDER_PORT}, "
        f"{_PLACEHOLDER_CIPHER}, {_PLACEHOLDER_PASSWORD}, tfo=true"
    )


def _blocked_surge_line(block_reason: BlockReason | None) -> str:
    return _blocked_surge_line_msg(_safe_proxy_name(blocked_message(block_reason)))


def _blocked_surge(block_reason: BlockReason | None) -> str:
    return _blocked_surge_msg(_safe_proxy_name(blocked_message(block_reason)))


def _blocked_surge_msg(message: str) -> str:
    line = _blocked_surge_line_msg(message)
    return f"#!MANAGED-CONFIG interval=86400\n\n[Proxy]\n{line}\n"


def _blocked_loon(block_reason: BlockReason | None) -> str:
    return _blocked_loon_msg(_safe_proxy_name(blocked_message(block_reason)))


def _blocked_loon_msg(message: str) -> str:
    line = _blocked_surge_line_msg(message)
    return f"[Proxy]\n{line}\n"


def _blocked_quantumult(block_reason: BlockReason | None) -> str:
    return _blocked_quantumult_msg(_safe_proxy_name(blocked_message(block_reason)))


def _blocked_quantumult_msg(message: str) -> str:
    """Quantumult X reads vmess:// lines; ps field is the visible name."""
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
