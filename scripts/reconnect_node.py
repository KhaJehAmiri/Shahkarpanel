#!/usr/bin/env python3
"""Reconnect a node and start Xray with the current effective config."""
from __future__ import annotations

import argparse
import sys
import time

_ROOT = __file__.rsplit("/", 2)[0] if "/scripts/" in __file__ else "."
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT if _ROOT != "." else "/code")

from app import xray
from app.db import GetDB, crud
from app.services.xray_node import build_node_xray_config
from app.xray.operations import (
    _mark_wg_node_connected,
    _sync_wireguard_node,
    add_node,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("node_id", type=int, nargs="?", default=1)
    args = parser.parse_args()
    node_id = args.node_id

    with GetDB() as db:
        dbn = crud.get_node_by_id(db, node_id)
    if not dbn:
        print(f"node {node_id} not found")
        return 1

    if node_id in xray.nodes:
        try:
            xray.nodes[node_id].disconnect()
        except Exception:
            pass
        del xray.nodes[node_id]

    node = add_node(dbn)
    cfg = build_node_xray_config(node_id)
    warp_rules = [
        r
        for r in (cfg.get("routing") or {}).get("rules", [])
        if r.get("outboundTag") == "warp"
    ]
    print(f"node={dbn.name} config_bytes={len(cfg.to_json())} warp_rules={len(warp_rules)}")

    print("connecting rpyc...")
    node.connect()
    print("rpyc ok")

    exc = None
    ver = None
    for attempt in range(1, 4):
        print(f"attempt {attempt}...")
        try:
            node.connect()
            try:
                node.remote.stop()
                time.sleep(0.5)
            except Exception:
                pass
            node.started = False
            node._api = None
            t0 = time.time()
            node.start(cfg)
            ver = node.get_version()
            print(f"xray ok version={ver} elapsed={time.time() - t0:.1f}s")
            exc = None
            break
        except Exception as e:
            exc = e
            print(f"xray failed: {type(e).__name__}: {e}")
            try:
                node.disconnect()
            except Exception:
                pass
            node.started = False
            time.sleep(3)

    if exc:
        _mark_wg_node_connected(node_id, node, xray_exc=exc, xray_version=ver)
    else:
        from app.models.node import NodeStatus
        from app.xray.operations import _change_node_status

        _change_node_status(node_id, NodeStatus.connected, message=None, version=ver)
        _sync_wireguard_node(node_id, node)

    with GetDB() as db:
        dbn = crud.get_node_by_id(db, node_id)
        print(f"status={dbn.status} message={dbn.message!r} version={dbn.xray_version}")
    print(f"connected={node.connected} started={node.started}")
    return 0 if not exc else 2


if __name__ == "__main__":
    raise SystemExit(main())
