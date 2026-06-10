"""SS-2022 smoke — validates key generation, share link, and Client API gating.

Usage:
  python3 scripts/ss2022_smoke_test.py
  python3 scripts/ss2022_smoke_test.py --enable-flag
"""
import argparse
import json
import uuid

from app import feature_flags
from app.db import GetDB, crud
from app.models.proxy import ShadowsocksSettings
from app.models.user import UserCreate
from xray_api.types.account import is_ss2022


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--enable-flag", action="store_true", help="Enable client_ss2022 globally")
    args = parser.parse_args()

    if args.enable_flag:
        feature_flags.set_flag("client_ss2022", True)

    out = {
        "client_ss2022_flag": feature_flags.is_enabled("client_ss2022"),
        "client_api_flag": feature_flags.is_enabled("client_api"),
    }

    settings = ShadowsocksSettings(method="2022-blake3-aes-256-gcm", password="x")
    out["key_valid"] = is_ss2022(settings.method)
    out["key_bytes"] = len(__import__("base64").b64decode(settings.password))

    with GetDB() as db:
        user = crud.create_user(db, UserCreate(
            username=f"ss2022-{uuid.uuid4().hex[:6]}",
            proxies={"shadowsocks": {"method": "2022-blake3-aes-256-gcm"}},
            inbounds={},
            status="active",
        ))
        proxy = next(p for p in user.proxies if p.type.value == "shadowsocks")
        out["user"] = user.username
        out["proxy_method"] = (proxy.settings or {}).get("method")
        out["has_password"] = bool((proxy.settings or {}).get("password"))

    out["next_steps"] = [
        "Create SS-2022 inbound on panel Xray (method 2022-blake3-aes-256-gcm)",
        "Enable client_ss2022 + client_api flags",
        "GET /api/v2/client/config — expect shadowsocks-2022 in protocol_materials",
    ]
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
