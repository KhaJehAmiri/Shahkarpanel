#!/usr/bin/env python3
"""Kill stale node Xray on :1080, patch agent, reconnect relays."""
from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

from app import xray
from app.db import GetDB, crud
from app.provisioning import SSHCredentials, run_remote_command
from app.provisioning.node_ssh import resolve_node_ssh
from app.xray import operations

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "node" / "xray.py"


def patch_node(host: str, *, password: str | None = None) -> str:
    body_b64 = base64.b64encode(PATCH.read_bytes()).decode()
    creds = (
        SSHCredentials(host=host, port=22, username="root", password=password)
        if password
        else resolve_node_ssh(host)
    )
    cmd = (
        "python3 -c \"import base64; open('/tmp/xray.py','wb').write(base64.b64decode('"
        + body_b64
        + "'))\" && docker cp /tmp/xray.py nexusnode:/code/xray.py && docker restart nexusnode"
    )
    return run_remote_command(creds, cmd, timeout=120) or "ok"


def prep(host: str, *, password: str | None = None) -> str:
    creds = (
        SSHCredentials(host=host, port=22, username="root", password=password)
        if password
        else resolve_node_ssh(host)
    )
    cmd = (
        "docker exec nexusnode sh -c '"
        "for pid in $(pgrep -f \"^/usr/local/bin/xray run -config stdin:\" 2>/dev/null); do kill -TERM \"$pid\" 2>/dev/null || true; done; "
        "ip link del wg0 2>/dev/null || true; ip link del wg1 2>/dev/null || true; "
        "echo XRAY=$(pgrep -c -f \"^/usr/local/bin/xray run\" 2>/dev/null || echo 0); "
        "ss -ltnp 2>/dev/null | grep 1080 || echo 1080-free'"
    )
    return run_remote_command(creds, cmd, timeout=25) or ""


def main() -> int:
    nodes = [(1, None), (44, "Faupload2012!")]
    with GetDB() as db:
        for nid, pw in nodes:
            n = crud.get_node_by_id(db, nid)
            print(f"patch {n.name} ({n.address}) ...", flush=True)
            print(patch_node(n.address, password=pw)[-400:], flush=True)
            time.sleep(15)
            try:
                print(f"prep {n.name}:", prep(n.address, password=pw), flush=True)
            except Exception as exc:
                print(f"prep {n.name} skipped: {exc}", flush=True)

    for nid, _pw in nodes:
        print(f"reconnect node {nid} ...", flush=True)
        operations.remove_node(nid)
        time.sleep(2)
        operations.connect_node(nid)
        time.sleep(35)

    report = {}
    with GetDB() as db:
        for nid, pw in nodes:
            n = crud.get_node_by_id(db, nid)
            node = xray.nodes.get(nid)
            report[nid] = {
                "status": str(n.status),
                "message": n.message,
                "connected": bool(node and node.connected),
                "remote": prep(n.address, password=pw),
            }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
