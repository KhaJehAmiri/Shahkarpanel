#!/usr/bin/env python3
"""One-shot: Reality + SS-2022 + tunnel loopback + user wiring + core restart.

Run from repo root:
  PYTHONPATH=/opt/nexuspanel python3 scripts/setup_panel_stack.py
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import tunnel as tunnel_svc
from app import xray
from app.db import GetDB, crud
from app.db.models import Proxy, Tunnel
from app.models.proxy import ProxyTypes, random_ss2022_key
from app.models.user import UserModify
from app.xray.config import XRayConfig
from config import XRAY_EXECUTABLE_PATH, XRAY_JSON
from xray_api.types.account import ShadowsocksMethods


def _x25519() -> dict:
    proc = subprocess.run(
        [XRAY_EXECUTABLE_PATH, "x25519"],
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    private_key = public_key = ""
    for line in proc.stdout.splitlines():
        low = line.lower()
        if "private" in low and ":" in line:
            private_key = line.split(":", 1)[1].strip()
        if "password" in low and ":" in line:
            public_key = line.split(":", 1)[1].strip()
        elif "public" in low and ":" in line:
            public_key = line.split(":", 1)[1].strip()
    if not private_key or not public_key:
        raise RuntimeError(f"x25519 parse failed: {proc.stdout!r}")
    return {"private_key": private_key, "public_key": public_key}


def _load_config() -> dict:
    import commentjson

    with open(XRAY_JSON) as f:
        return commentjson.loads(f.read())


def _save_and_restart(payload: dict) -> None:
    config = XRayConfig(payload, api_port=xray.config.api_port)
    xray.config = config
    with open(XRAY_JSON, "w") as f:
        f.write(json.dumps(payload, indent=4))
    startup = xray.config.include_db_users()
    xray.core.restart(startup)
    xray.hosts.update()


def _ensure_reality_inbound(cfg: dict) -> dict:
    keys = _x25519()
    short_id = secrets.token_hex(4)
    dest = "www.google.com:443"
    sni = "www.google.com"

    updated = False
    for inbound in cfg.get("inbounds", []):
        if inbound.get("tag") == "VLESS TCP":
            inbound["streamSettings"] = {
                "network": "tcp",
                "security": "reality",
                "realitySettings": {
                    "show": False,
                    "dest": dest,
                    "xver": 0,
                    "serverNames": [sni],
                    "privateKey": keys["private_key"],
                    "publicKey": keys["public_key"],
                    "shortIds": [short_id, ""],
                },
            }
            inbound.setdefault("sniffing", {
                "enabled": True,
                "destOverride": ["http", "tls", "quic"],
            })
            updated = True
            break

    if not updated:
        cfg.setdefault("inbounds", []).append({
            "tag": "VLESS REALITY",
            "listen": "0.0.0.0",
            "port": 8443,
            "protocol": "vless",
            "settings": {"clients": [], "decryption": "none"},
            "streamSettings": {
                "network": "tcp",
                "security": "reality",
                "realitySettings": {
                    "show": False,
                    "dest": dest,
                    "xver": 0,
                    "serverNames": [sni],
                    "privateKey": keys["private_key"],
                    "publicKey": keys["public_key"],
                    "shortIds": [short_id, ""],
                },
            },
            "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"]},
        })

    return {
        "reality": True,
        "public_key": keys["public_key"],
        "short_id": short_id,
        "sni": sni,
        "port": 8443,
    }


def _ensure_ss2022_inbound(cfg: dict) -> dict:
    server_psk = random_ss2022_key(ShadowsocksMethods.BLAKE3_AES_256_GCM)
    method = "2022-blake3-aes-256-gcm"
    tag = "SS-2022"

    found = False
    for inbound in cfg.get("inbounds", []):
        if inbound.get("tag") == tag:
            inbound["settings"]["method"] = method
            inbound["settings"]["password"] = server_psk
            inbound["settings"].setdefault("network", "tcp,udp")
            inbound["settings"]["clients"] = []
            found = True
            break

    if not found:
        cfg.setdefault("inbounds", []).append({
            "tag": tag,
            "listen": "0.0.0.0",
            "port": 8388,
            "protocol": "shadowsocks",
            "settings": {
                "method": method,
                "password": server_psk,
                "network": "tcp,udp",
                "clients": [],
            },
        })

    return {"tag": tag, "method": method, "server_psk": server_psk, "port": 8388}


def _wire_alireza(reality_tag: str, ss_tag: str) -> None:
    with GetDB() as db:
        user = crud.get_user(db, "alireza")
        if not user:
            print("skip user: alireza not found")
            return

        inbounds = dict(user.inbounds or {})
        vless_tags = list(inbounds.get(ProxyTypes.VLESS, []) or [])
        if reality_tag not in vless_tags:
            vless_tags.insert(0, reality_tag)
        inbounds[ProxyTypes.VLESS] = vless_tags

        # SS-2022 users must not be placed on legacy shadowsocks inbounds.
        inbounds[ProxyTypes.Shadowsocks] = [ss_tag]

        user_key = random_ss2022_key(ShadowsocksMethods.BLAKE3_AES_256_GCM)
        crud.update_user(
            db,
            user,
            UserModify(
                inbounds=inbounds,
                proxies={
                    ProxyTypes.VLESS: {"flow": "xtls-rprx-vision"},
                    ProxyTypes.Shadowsocks: {
                        "method": "2022-blake3-aes-256-gcm",
                        "password": user_key,
                    },
                },
            ),
        )
        db.commit()
        print("alireza: reality + ss2022 wired")


def _ensure_tunnel() -> int:
    params = tunnel_svc.default_params("reality")
    tunnel_svc.ensure_reality_keys(params)
    with GetDB() as db:
        existing = (
            db.query(Tunnel)
            .filter(Tunnel.name == "panel-loopback-e2e")
            .first()
        )
        if existing:
            existing.enabled = True
            existing.relay_node_id = None
            existing.exit_node_id = None
            existing.transport = "reality"
            existing.listen_port = 9443
            existing.target_port = 9443
            existing.params = params
            db.commit()
            db.refresh(existing)
            return existing.id

        t = Tunnel(
            name="panel-loopback-e2e",
            enabled=True,
            relay_node_id=None,
            exit_node_id=None,
            transport="reality",
            listen_port=9443,
            target_port=9443,
            params=params,
        )
        db.add(t)
        db.commit()
        db.refresh(t)
        return t.id


def _apply_tunnel() -> None:
    startup = xray.config.include_db_users()
    xray.core.restart(startup)


def _exclude_ss2022_from_legacy_users() -> int:
    """Legacy chacha20 users must not receive the SS-2022 inbound in subscriptions."""
    from app.db.models import Proxy, User
    from xray_api.types.account import is_ss2022

    changed = 0
    with GetDB() as db:
        ss2022 = crud.get_or_create_inbound(db, "SS-2022")
        for user in db.query(User).all():
            if user.username == "alireza":
                continue
            for proxy in user.proxies:
                if proxy.type != ProxyTypes.Shadowsocks.value:
                    continue
                method = (proxy.settings or {}).get("method") or ""
                if is_ss2022(method):
                    continue
                have = {i.tag for i in proxy.excluded_inbounds}
                if "SS-2022" in have:
                    continue
                proxy.excluded_inbounds = list(proxy.excluded_inbounds) + [ss2022]
                changed += 1
        db.commit()
    return changed


def main():
    out = {}
    cfg = _load_config()
    out["reality"] = _ensure_reality_inbound(cfg)
    out["ss2022"] = _ensure_ss2022_inbound(cfg)
    _save_and_restart(cfg)
    out["xray_restarted"] = True

    reality_tag = "VLESS TCP"
    _wire_alireza(reality_tag, out["ss2022"]["tag"])
    out["legacy_ss_exclusions"] = _exclude_ss2022_from_legacy_users()

    tid = _ensure_tunnel()
    out["tunnel_id"] = tid
    _apply_tunnel()
    out["tunnel_applied"] = True

    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
