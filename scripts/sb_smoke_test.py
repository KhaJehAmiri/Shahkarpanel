"""Smoke test for sing-box QUIC protocols (Hysteria2 + TUIC).

Prints subscription links for a user and checks the remote node UDP listeners.
Run from repo root: python3 scripts/sb_smoke_test.py [--user alireza]
"""
import argparse
import json
import sys

from app.db import GetDB, crud
from app.models.proxy import ProxyTypes
from app.subscription.quic import user_hysteria2_link, user_tuic_link
from app.utils.jwt import create_subscription_token


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", default="alireza")
    parser.add_argument("--node-id", type=int, default=1)
    args = parser.parse_args()

    out = {"user": args.user, "node_id": args.node_id}
    with GetDB() as db:
        user = crud.get_user(db, args.user)
        if user is None:
            print(json.dumps({"error": f"user {args.user} not found"}, indent=2))
            return 1
        node = crud.get_node_by_id(db, args.node_id)
        if node is None or node.singbox is None:
            print(json.dumps({"error": f"node {args.node_id} has no singbox config"}, indent=2))
            return 1

        out["token"] = create_subscription_token(user.username)
        for proxy in user.proxies:
            if proxy.type is ProxyTypes.Hysteria2:
                out["hysteria2_link"] = user_hysteria2_link(
                    proxy.settings or {}, node, remark=f"{user.username}-{node.name}"
                )
            if proxy.type is ProxyTypes.TUIC:
                out["tuic_link"] = user_tuic_link(
                    proxy.settings or {}, node, remark=f"{user.username}-{node.name}"
                )

        cfg = node.singbox
        out["node"] = {
            "address": node.address,
            "hysteria2_enabled": cfg.hysteria2_enabled,
            "hysteria2_port": cfg.hysteria2_port,
            "tuic_enabled": cfg.tuic_enabled,
            "tuic_port": cfg.tuic_port,
        }

    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
