#!/usr/bin/env python3
"""Rebuild relay node agents, reconnect, apply tunnels, verify egress."""
from __future__ import annotations

import json
import sys
import time

from app import provisioning, xray
from app.db import GetDB, crud
from app.db.models import Tunnel
from app.provisioning import SSHCredentials
from app.provisioning.node_ssh import resolve_node_ssh
from app.routers.tunnel import _apply_tunnel
from app.singbox.operations import sync_node as singbox_sync
from app.wireguard.operations import sync_node as wg_sync
from app.xray import operations
from app.xray.operations import get_tls
from config import NODE_AGENT_IMAGE, NODE_BOOTSTRAP_TOKEN, NODE_CONTROL_SECRET


def rebuild_agent(dbnode, *, password: str | None = None) -> None:
    panel_url = provisioning.resolve_panel_public_url()
    try:
        client_cert_pem = get_tls()["certificate"]
    except Exception:
        client_cert_pem = None

    cmd = provisioning.build_install_command(
        panel_url,
        NODE_BOOTSTRAP_TOKEN,
        dbnode.name,
        role=dbnode.role or "relay",
        core_kind=dbnode.core_kind or "wireguard",
        region=dbnode.region,
        image=NODE_AGENT_IMAGE,
        control_secret=NODE_CONTROL_SECRET or None,
        force_image_rebuild=True,
        client_cert_pem=client_cert_pem,
        include_awg=True,
    )
    refresh = (
        "set -e; "
        + cmd.split("docker rm -f nexusnode", 1)[0]
        + cmd[cmd.index("docker rm -f nexusnode") :]
    )
    if "curl -fsSL" in refresh:
        head, tail = refresh.rsplit("curl -fsSL", 1)
        refresh = head + "(curl -fsSL" + tail + ") || true"

    if password:
        creds = SSHCredentials(host=dbnode.address, port=22, username="root", password=password)
    else:
        creds = resolve_node_ssh(dbnode.address)

    print(f"rebuilding {dbnode.name} ({dbnode.address}) ...", flush=True)
    out = provisioning.run_remote_command(creds, refresh, exec_timeout=1800)
    print((out or "done")[-400:], flush=True)


def wait_connected(node_id: int, timeout: float = 90.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with GetDB() as db:
            n = crud.get_node_by_id(db, node_id)
            if n and str(n.status).endswith("connected") and not (n.message or "").startswith("WireGuard active"):
                return True
            if n and str(n.status).endswith("connected") and n.message is None:
                return True
        time.sleep(3)
    return False


def connect_and_sync(node_id: int) -> dict:
    operations.remove_node(node_id)
    operations.connect_node(node_id)
    time.sleep(25)
    result = {"node_id": node_id, "connected": False, "wg": False, "singbox": False}
    with GetDB() as db:
        n = crud.get_node_by_id(db, node_id)
        result["status"] = str(n.status)
        result["message"] = n.message
        node = xray.nodes.get(node_id)
        if node and node.connected:
            result["connected"] = True
            result["wg"] = bool(wg_sync(db, n, node_object=node))
            result["singbox"] = bool(singbox_sync(db, n, node_object=node))
    return result


def remote_state(host: str, *, password: str | None = None) -> dict:
    cmd = (
        "docker exec nexusnode sh -c '"
        "pgrep -c xray 2>/dev/null || echo 0; "
        "pgrep -c sing-box 2>/dev/null || echo 0; "
        "ss -ltn 2>/dev/null | grep -E \"18004|18006\" || true; "
        "ss -lun 2>/dev/null | grep 51820 || true; "
        "python3 -c \"import json;c=json.load(open(\\\"/var/lib/nexusnode/singbox.json\\\"));"
        "print(c[\\\"route\\\"].get(\\\"final\\\"), c[\\\"outbounds\\\"][0].get(\\\"type\\\"))\" 2>/dev/null || true"
        "'"
    )
    try:
        if password:
            creds = SSHCredentials(host=host, port=22, username="root", password=password)
        else:
            creds = resolve_node_ssh(host)
        out = provisioning.run_remote_command(creds, cmd, timeout=30)
        lines = (out or "").strip().splitlines()
        state = {"raw": lines}
        nums = [ln for ln in lines if ln.strip().isdigit()]
        if len(nums) >= 2:
            state["xray"] = int(nums[0])
            state["singbox"] = int(nums[1])
        for ln in lines:
            if ln.startswith("tunnel-"):
                state["sb_final"] = ln.split()[0]
                if len(ln.split()) > 1:
                    state["sb_out_type"] = ln.split()[1]
            if "18004" in ln or "18006" in ln:
                state["socks"] = True
            if ":51820" in ln:
                state["wg51820"] = True
        return state
    except Exception as exc:
        return {"error": str(exc)}


def egress_smoke(host: str, socks_port: int, *, password: str | None = None) -> str:
    script = f"""python3 - <<'PY'
import json, subprocess, time, urllib.request
cfg={{"log":{{"level":"error"}},"inbounds":[{{"type":"http","listen":"127.0.0.1","listen_port":19080}}],"outbounds":[{{"type":"socks","tag":"proxy","server":"127.0.0.1","server_port":{socks_port},"version":"5"}}],"route":{{"final":"proxy"}}}}
open("/tmp/eg.json","w").write(json.dumps(cfg))
subprocess.run(["pkill","-f","/tmp/eg.json"], stderr=subprocess.DEVNULL)
p=subprocess.Popen(["sing-box","run","-c","/tmp/eg.json"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(4)
try:
  pr=urllib.request.ProxyHandler({{"http":"http://127.0.0.1:19080","https":"http://127.0.0.1:19080"}})
  o=urllib.request.build_opener(pr)
  print(o.open("https://api.ipify.org", timeout=15).read().decode().strip())
except Exception as e:
  print("ERR:"+str(e))
finally:
  p.terminate()
PY"""
    try:
        if password:
            creds = SSHCredentials(host=host, port=22, username="root", password=password)
        else:
            creds = resolve_node_ssh(host)
        out = provisioning.run_remote_command(
            creds,
            f"docker exec nexusnode sh -c {json.dumps(script)}",
            timeout=40,
        )
        return (out or "").strip().splitlines()[-1] if out else "ERR:empty"
    except Exception as exc:
        return f"ERR:{exc}"


def main() -> int:
    report: dict = {"steps": []}
    nodes = [
        (1, None),
        (44, "Faupload2012!"),
    ]

    with GetDB() as db:
        for nid, pw in nodes:
            n = crud.get_node_by_id(db, nid)
            try:
                rebuild_agent(n, password=pw)
                report["steps"].append({"rebuild": nid, "ok": True})
            except Exception as exc:
                report["steps"].append({"rebuild": nid, "ok": False, "error": str(exc)})
                print(json.dumps(report, indent=2))
                return 1
            time.sleep(8)

        for nid, pw in nodes:
            conn = connect_and_sync(nid)
            report["steps"].append({"connect": nid, **conn})

        for t in db.query(Tunnel).filter(Tunnel.enabled.is_(True)).all():
            applied = _apply_tunnel(db, t, health=False)
            report["steps"].append({"apply_tunnel": t.id, **applied})

        for nid, pw in nodes:
            n = crud.get_node_by_id(db, nid)
            socks = 18004 if nid == 1 else 18006
            report["verify"] = report.get("verify", [])
            report["verify"].append(
                {
                    "node_id": nid,
                    "remote": remote_state(n.address, password=pw),
                    "egress_ip": egress_smoke(n.address, socks, password=pw),
                    "expected": "91.220.8.251",
                }
            )

    ok = all(
        v.get("egress_ip") == "91.220.8.251"
        for v in report.get("verify", [])
    )
    report["verdict"] = "PASS" if ok else "FAIL"
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
