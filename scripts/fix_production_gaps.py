#!/usr/bin/env python3
"""One-shot production fixes after panel stack setup.

- Disable the loopback E2E tunnel (not for live users).
- Persist SS-2022 exclusions on legacy Shadowsocks users.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.db import GetDB, crud
from app.db.crud import get_or_create_inbound
from app.db.models import Proxy, Tunnel, User
from app.models.proxy import ProxyTypes
from xray_api.types.account import is_ss2022


def _disable_loopback_tunnel(db) -> bool:
    t = db.query(Tunnel).filter(Tunnel.name == "panel-loopback-e2e").first()
    if not t or not t.enabled:
        return False
    t.enabled = False
    db.commit()
    print("disabled tunnel panel-loopback-e2e")
    return True


def _fix_legacy_ss_exclusions(db) -> int:
    changed = 0
    ss2022 = get_or_create_inbound(db, "SS-2022")
    for user in db.query(User).all():
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
            print(f"exclude SS-2022 for {user.username}")
    if changed:
        db.commit()
    return changed


def main():
    with GetDB() as db:
        tunnel = _disable_loopback_tunnel(db)
        users = _fix_legacy_ss_exclusions(db)
    print(f"done tunnel={tunnel} users_fixed={users}")


if __name__ == "__main__":
    main()
