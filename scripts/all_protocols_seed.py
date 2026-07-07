#!/usr/bin/env python3
"""Seed one smoke inbound per Add-Inbound protocol + test user + hosts.

Usage:
  PYTHONPATH=. python3 scripts/all_protocols_seed.py
  PYTHONPATH=. python3 scripts/all_protocols_seed.py --restart
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

XRAY_JSON = Path("/var/lib/nexuspanel/xray_config.json")
SMOKE_USER = "smoke_all"


def reload_xray_config() -> None:
    from app import xray

    xray.config = xray._load_xray_config(xray.config.api_port)
    xray.refresh_for_subscription()


def purge_smoke_inbounds() -> list[str]:
    """Remove smoke-* inbounds from the live Xray config (restores core after seed tests)."""
    from tests.helpers.all_protocol_inbounds import SMOKE_TAG_PREFIX

    if not XRAY_JSON.is_file():
        raise SystemExit(f"missing {XRAY_JSON}")

    raw = json.loads(XRAY_JSON.read_text(encoding="utf-8"))
    removed = [
        str(ib.get("tag"))
        for ib in (raw.get("inbounds") or [])
        if str(ib.get("tag") or "").startswith(SMOKE_TAG_PREFIX)
    ]
    raw["inbounds"] = [
        ib for ib in (raw.get("inbounds") or [])
        if not str(ib.get("tag") or "").startswith(SMOKE_TAG_PREFIX)
    ]
    XRAY_JSON.write_text(json.dumps(raw, indent=4), encoding="utf-8")
    return removed


    from app.xray.inbound_normalize import normalize_core_config_payload
    from tests.helpers.all_protocol_inbounds import (
        CONFIG_ONLY_PROTOCOLS,
        SMOKE_TAG_PREFIX,
        all_smoke_inbounds,
        build_smoke_context,
        patch_freedom_for_smoke,
    )

    if not XRAY_JSON.is_file():
        raise SystemExit(f"missing {XRAY_JSON}")

    ctx = build_smoke_context()
    fresh = {
        ib["tag"]: ib
        for ib in all_smoke_inbounds(ctx, include_config_only=include_config_only)
    }
    raw = json.loads(XRAY_JSON.read_text(encoding="utf-8"))
    kept = [
        ib for ib in (raw.get("inbounds") or [])
        if not str(ib.get("tag") or "").startswith(SMOKE_TAG_PREFIX)
    ]
    kept.extend(fresh.values())
    raw["inbounds"] = kept
    normalized = normalize_core_config_payload(raw)
    patch_freedom_for_smoke(normalized)
    XRAY_JSON.write_text(json.dumps(normalized, indent=4), encoding="utf-8")
    if not include_config_only:
        skipped = sorted(CONFIG_ONLY_PROTOCOLS)
        if skipped:
            print(f"skipped config-only inbounds (use --with-tun): {', '.join(skipped)}")
    return sorted(fresh.keys())


def ensure_smoke_user(tags: list[str]) -> str:
    from app.db import GetDB, crud
    from app.models.proxy import ProxyTypes
    from app.models.user import UserCreate, UserStatus

    proto_map = {
        "vless": ProxyTypes.VLESS,
        "vmess": ProxyTypes.VMess,
        "trojan": ProxyTypes.Trojan,
        "shadowsocks": ProxyTypes.Shadowsocks,
    }
    inbounds: dict = {}
    proxies: dict = {}
    for tag in tags:
        proto = tag.replace("smoke-", "", 1)
        ptype = proto_map.get(proto)
        if not ptype:
            continue
        inbounds[ptype] = [tag]
        proxies[ptype] = {}

    with GetDB() as db:
        existing = crud.get_user(db, SMOKE_USER)
        if existing:
            from app.models.user import UserModify

            crud.update_user(
                db,
                existing,
                UserModify(proxies=proxies, inbounds=inbounds, status=UserStatus.active),
            )
            db.commit()
            return SMOKE_USER

        username = SMOKE_USER
        if crud.get_user(db, username):
            username = f"smoke_{uuid.uuid4().hex[:8]}"
        crud.create_user(
            db,
            UserCreate(
                username=username,
                proxies=proxies,
                inbounds=inbounds,
                status=UserStatus.active,
            ),
            admin=None,
        )
        return username


def ensure_hosts(tags: list[str]) -> None:
    from app.db import GetDB, crud
    from app.models.proxy import ProxyHost
    from tests.helpers.all_protocol_inbounds import SMOKE_SNI, smoke_inbound_by_tag

    with GetDB() as db:
        for tag in tags:
            ib = smoke_inbound_by_tag(tag)
            if not ib:
                continue
            port = int(ib.get("port") or 0)
            if port <= 0:
                continue
            remark = f"smoke ({tag})"
            hosts = crud.get_hosts(db, tag)
            if any(h.remark == remark for h in hosts):
                continue
            crud.add_host(
                db,
                tag,
                ProxyHost(
                    remark=remark,
                    address=SMOKE_SNI,
                    port=port,
                    allowinsecure=True,
                ),
            )


def xray_test() -> int:
    proc = subprocess.run(
        ["xray", "run", "-test", "-config", str(XRAY_JSON)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        print((proc.stderr or proc.stdout)[-1200:])
    else:
        print("xray -test OK")
    return proc.returncode


def restart_panel() -> None:
    subprocess.run(["pkill", "-9", "xray"], check=False)
    time.sleep(1)
    names = subprocess.check_output(
        ["docker", "ps", "--format", "{{.Names}}"],
        text=True,
    )
    for line in names.splitlines():
        if "nexuspanel" in line and "postgres" not in line and "redis" not in line:
            subprocess.run(["docker", "restart", line], check=False)
            print(f"restarted {line}")
            return
    print("panel container not found — restart manually")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--purge-smoke",
        action="store_true",
        help="Remove smoke-* inbounds from live config (no seed)",
    )
    parser.add_argument("--restart", action="store_true", help="Restart panel container after seed")
    parser.add_argument(
        "--with-tun",
        action="store_true",
        help="Include TUN inbound (needs /dev/net/tun; breaks Docker Xray by default)",
    )
    args = parser.parse_args()

    if args.purge_smoke:
        removed = purge_smoke_inbounds()
        print(f"purged smoke inbounds: {', '.join(removed) or '(none)'}")
        reload_xray_config()
        rc = xray_test()
        if args.restart:
            restart_panel()
        return rc

    tags = merge_smoke_inbounds(include_config_only=args.with_tun)
    print(f"smoke inbounds: {', '.join(tags)}")
    reload_xray_config()
    username = ensure_smoke_user(tags)
    print(f"smoke user: {username}")
    ensure_hosts(tags)
    print("hosts: OK")

    rc = xray_test()
    if rc != 0:
        return rc

    if args.restart:
        restart_panel()
    else:
        print("Note: restart panel to load config:")
        print("  docker compose restart nexuspanel")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
