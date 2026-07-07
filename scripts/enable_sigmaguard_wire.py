#!/usr/bin/env python3
"""Enable SigmaGuard Wire flags and apply preset on all WireGuard nodes."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.environ.get("PYTHONPATH", "/opt/nexuspanel"))

from app import feature_flags
from app.db import GetDB, crud
from app.models.node import CoreKind
from app.wireguard.operations import sync_node


def main() -> int:
    feature_flags.set_flag("client_api", True)
    feature_flags.set_flag("sigmaguard_wire", True)
    print("feature flags: client_api=on sigmaguard_wire=on")

    with GetDB() as db:
        nodes = crud.get_wireguard_nodes(db, enabled_only=False)
        for node in nodes:
            if node.core_kind != CoreKind.wireguard.value or not node.wireguard:
                continue
            try:
                crud.set_node_sg_wire(db, node, enabled=True)
                sync_node(db, node)
                print(f"  node {node.id} {node.name}: sg_wire enabled + synced")
            except Exception as exc:
                print(f"  node {node.id} {node.name}: skip ({exc})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
