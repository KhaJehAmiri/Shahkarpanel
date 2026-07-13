#!/usr/bin/env python3
import json
import time

from app import xray
from app.db import GetDB, crud
from app.db.models import Tunnel
from app.provisioning import SSHCredentials, run_remote_command
from app.provisioning.node_ssh import resolve_node_ssh
from app.routers.tunnel import _apply_tunnel
from app.xray import operations


def prep(host, pw=None):
    cmd = (
        "docker exec nexusnode sh -c "
        "'ip link del wg0 2>/dev/null; ip link del wg1 2>/dev/null; true'"
    )
    creds = (
        SSHCredentials(host=host, port=22, username="root", password=pw)
        if pw
        else resolve_node_ssh(host)
    )
    run_remote_command(creds, cmd, timeout=20)


def remote_check(host, pw=None):
    cmd = (
        "docker exec nexusnode sh -c "
        "'echo XRAY=$(pgrep -c xray || echo 0); echo SB=$(pgrep -c sing-box || echo 0); "
        "ss -ltn | grep -E 18004|18006 || true; ss -lun | grep 51820 || true; "
        "python3 -c \"import json;c=json.load(open(\\\"/var/lib/nexusnode/singbox.json\\\"));"
        "print(c[\\\"route\\\"].get(\\\"final\\\"), c[\\\"outbounds\\\"][0].get(\\\"type\\\"))\"'"
    )
    creds = (
        SSHCredentials(host=host, port=22, username="root", password=pw)
        if pw
        else resolve_node_ssh(host)
    )
    return run_remote_command(creds, cmd, timeout=25)


def main():
    nodes = [(1, None), (44, "Faupload2012!")]
    for nid, pw in nodes:
        with GetDB() as db:
            n = crud.get_node_by_id(db, nid)
            prep(n.address, pw)
        operations.remove_node(nid)
        time.sleep(2)
        operations.connect_node(nid)
        time.sleep(35)

    with GetDB() as db:
        for t in db.query(Tunnel).filter(Tunnel.enabled.is_(True)).all():
            print("apply", t.id, _apply_tunnel(db, t, health=False))
        time.sleep(25)
        report = {"nodes": [], "registry": list(xray.nodes.keys())}
        for nid, pw in nodes:
            n = crud.get_node_by_id(db, nid)
            report["nodes"].append(
                {
                    "id": nid,
                    "status": str(n.status),
                    "message": n.message,
                    "remote": remote_check(n.address, pw),
                    "live_connected": bool(
                        xray.nodes.get(nid) and xray.nodes[nid].connected
                    ),
                }
            )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
