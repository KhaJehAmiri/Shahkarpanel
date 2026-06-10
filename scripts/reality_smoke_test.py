"""VLESS+Reality smoke — x25519 keygen + subscription link checklist.

Usage:
  python3 scripts/reality_smoke_test.py
"""
import json
import uuid

from app.db import GetDB, crud
from app.models.user import UserCreate
from app.utils.jwt import create_subscription_token


def main():
    out = {}
    try:
        from app import xray
        keys = xray.core.get_x25519()
        out["x25519"] = {"public_key": keys["public_key"][:16] + "…"} if keys else None
    except Exception as exc:
        out["x25519_error"] = str(exc)

    with GetDB() as db:
        user = crud.create_user(db, UserCreate(
            username=f"reality-{uuid.uuid4().hex[:6]}",
            proxies={"vless": {"flow": "xtls-rprx-vision"}},
            inbounds={},
            status="active",
        ))
        token = create_subscription_token(user.username)
        out["user"] = user.username
        out["sub_token"] = token
        out["sub_url"] = f"/sub/{token}/"
        out["sub_info"] = f"/sub/{token}/info"

    out["setup_checklist"] = [
        "Inbounds UI → VLESS + TCP + Reality on port 443",
        "Generate Reality keypair in inbound editor",
        "Assign inbound tag to user's vless proxy",
        "Restart panel Xray core",
        f"curl /sub/{out.get('sub_token', 'TOKEN')}/ — expect vless:// with reality params",
        "GET /api/v2/client/config — expect vless-reality in protocol_materials",
    ]
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
