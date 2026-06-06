#!/usr/bin/env python3
"""Test WG data_limit: 1 GiB cap, fast external transfer from panel → WG node."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import paramiko
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PANEL = os.environ.get("WG_SMOKE_PANEL", "http://127.0.0.1:8000")
ADMIN_USER = os.environ.get("WG_SMOKE_ADMIN", "admin")
ADMIN_PASS = os.environ.get("WG_SMOKE_ADMIN_PASS", "changeme")
USERNAME = os.environ.get("WG_LIMIT_USERNAME", "wg_smoke_test")
NODE_ID = int(os.environ.get("WG_SMOKE_NODE_ID", "1"))
ONE_GIB = 1024**3
# Slightly over 1 GiB so limit definitely trips.
TARGET_GIB = float(os.environ.get("WG_LIMIT_TRANSFER_GIB", "1.05"))
SSH_PASS = os.environ.get("WG_NODE_SSH_PASSWORD", "")
IPERF_PORT = int(os.environ.get("WG_LIMIT_IPERF_PORT", "5201"))


def _token() -> str:
    r = requests.post(
        f"{PANEL}/api/admin/token",
        data={"username": ADMIN_USER, "password": ADMIN_PASS},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _headers(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _panel_ip() -> str:
    try:
        return requests.get("https://api.ipify.org", timeout=5).text.strip()
    except Exception:
        out = subprocess.check_output(["hostname", "-I"], text=True)
        return out.split()[0]


def _build_conf() -> tuple[str, str, str]:
    from app.db import GetDB, crud
    from app.models.proxy import ProxyTypes
    from app.subscription.wireguard import render_wireguard_conf, node_endpoint

    with GetDB() as db:
        u = crud.get_user(db, USERNAME)
        dbnode = crud.get_node_by_id(db, NODE_ID)
        proxy = next(p for p in u.proxies if p.type == ProxyTypes.WireGuard)
        settings = dict(proxy.settings or {})
        ep = node_endpoint(dbnode)
        conf = render_wireguard_conf(
            private_key=settings["private_key"],
            address=settings["address"],
            server_public_key=dbnode.wireguard.public_key,
            endpoint=ep,
            preshared_key=settings.get("preshared_key"),
            allowed_ips="10.10.0.1/32",
            mtu=dbnode.wireguard.mtu,
        )
        return conf, dbnode.address, ep


def _sync_wg():
    from app import xray
    from app.wireguard.operations import sync_all_nodes
    from app.xray import operations as xray_ops

    for _ in range(8):
        xray_ops.connect_node(NODE_ID)
        if NODE_ID in xray.nodes and xray.nodes[NODE_ID].connected:
            break
        time.sleep(3)
    sync_all_nodes()


def _wg_client_bytes() -> int:
    out = subprocess.check_output(["wg", "show", "all", "transfer"], text=True)
    total = 0
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0] != "wg0":
            total = int(parts[2]) + int(parts[3])
    return total


def _start_iperf_server(host: str) -> None:
    """Sink on WG node — bind to tunnel IP, client connects from panel externally."""
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username="root", password=SSH_PASS, timeout=20)
    try:
        ssh.exec_command(f"pkill -x iperf3 2>/dev/null; pkill -f 'iperf3 -s' 2>/dev/null || true")
        time.sleep(0.5)
        ssh.exec_command(
            f"nohup iperf3 -s -1 -p {IPERF_PORT} -B 10.10.0.1 > /tmp/iperf3-wg-limit.log 2>&1 &"
        )
        time.sleep(1)
    finally:
        ssh.close()


def _stop_iperf_server(host: str) -> None:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username="root", password=SSH_PASS, timeout=20)
    try:
        ssh.exec_command("pkill -x iperf3 2>/dev/null || true")
    finally:
        ssh.close()


def _fast_transfer_external(conf: str, host: str, gib: float) -> dict:
    """Client on panel host → public Endpoint; payload to 10.10.0.1 via tunnel."""
    _start_iperf_server(host)
    panel_ip = _panel_ip()
    result = {"panel_ip": panel_ip, "mode": "external-host-iperf3", "bytes": 0, "bitrate": None}

    with tempfile.TemporaryDirectory() as td:
        cp = Path(td) / "client.conf"
        cp.write_text(conf)
        subprocess.run(["wg-quick", "down", str(cp)], stderr=subprocess.DEVNULL)
        subprocess.run(["wg-quick", "up", str(cp)], check=True)
        try:
            time.sleep(6)
            hs = subprocess.check_output(["wg", "show", "all"], text=True)
            if "latest handshake" not in hs:
                raise RuntimeError("no WG handshake from panel to node")

            target_mb = int(gib * 1024)
            t0 = time.time()
            proc = subprocess.run(
                [
                    "iperf3", "-c", "10.10.0.1", "-p", str(IPERF_PORT),
                    "-n", f"{target_mb}M", "-J", "-P", "4",
                ],
                capture_output=True,
                text=True,
                timeout=600,
            )
            elapsed = time.time() - t0
            result["elapsed_s"] = round(elapsed, 1)
            result["wg_bytes"] = _wg_client_bytes()

            if proc.stdout:
                try:
                    data = json.loads(proc.stdout)
                    end = data.get("end", {})
                    sum_sent = end.get("sum_sent", {})
                    result["bytes"] = int(sum_sent.get("bytes", 0))
                    result["bitrate"] = sum_sent.get("bits_per_second")
                except json.JSONDecodeError:
                    pass
            if proc.returncode != 0 and not result["bytes"]:
                raise RuntimeError(proc.stderr[-500:] or proc.stdout[-500:] or "iperf3 failed")
        finally:
            subprocess.run(["wg-quick", "down", str(cp)], stderr=subprocess.DEVNULL)

    _stop_iperf_server(host)

    # Confirm node saw panel IP, not loopback.
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username="root", password=SSH_PASS, timeout=20)
    try:
        _, stdout, _ = ssh.exec_command("docker exec nexusnode wg show wg0")
        result["node_wg_show"] = stdout.read().decode()[-600:]
        if panel_ip in result["node_wg_show"]:
            result["external_ok"] = True
        elif "127.0.0.1" in result["node_wg_show"]:
            result["external_ok"] = False
    finally:
        ssh.close()

    return result


def _accounting_until(expected_min: int, timeout: int = 180) -> int:
    from app.jobs.record_usages import record_user_usages
    from app.db import GetDB, crud

    deadline = time.time() + timeout
    used = 0
    while time.time() < deadline:
        record_user_usages()
        with GetDB() as db:
            u = crud.get_user(db, USERNAME)
            used = int(u.used_traffic or 0)
        if used >= expected_min:
            return used
        time.sleep(2)
    return used


def main():
    if not SSH_PASS:
        print("WG_NODE_SSH_PASSWORD required", file=sys.stderr)
        sys.exit(2)
    if not shutil_which("iperf3"):
        print("iperf3 required on panel host", file=sys.stderr)
        sys.exit(2)

    tok = _token()
    print("== 0) Prepare user (reset if limited / over quota) ==")
    r = requests.get(f"{PANEL}/api/user/{USERNAME}", headers=_headers(tok), timeout=30)
    r.raise_for_status()
    cur = r.json()
    if cur.get("status") != "active" or int(cur.get("used_traffic") or 0) > 0:
        r = requests.post(f"{PANEL}/api/user/{USERNAME}/reset", headers=_headers(tok), timeout=30)
        r.raise_for_status()
        cur = r.json()
        _sync_wg()

    print("== 1) Set 1 GiB data_limit ==")
    r = requests.put(
        f"{PANEL}/api/user/{USERNAME}",
        headers=_headers(tok),
        json={"data_limit": ONE_GIB, "status": "active"},
        timeout=30,
    )
    r.raise_for_status()
    body = r.json()
    print(json.dumps({
        "data_limit": body.get("data_limit"),
        "used_traffic": body.get("used_traffic"),
        "status": body.get("status"),
    }, indent=2))

    print("== 2) Sync WG ==")
    _sync_wg()

    conf, host, endpoint = _build_conf()
    print(f"== 3) Fast external transfer panel → {endpoint} (target {TARGET_GIB} GiB) ==")
    xfer = _fast_transfer_external(conf, host, TARGET_GIB)
    print(json.dumps({
        "panel_ip": xfer.get("panel_ip"),
        "external_ok": xfer.get("external_ok"),
        "bytes": xfer.get("bytes"),
        "wg_bytes": xfer.get("wg_bytes"),
        "elapsed_s": xfer.get("elapsed_s"),
        "bitrate_mbps": round((xfer.get("bitrate") or 0) / 1e6, 1) if xfer.get("bitrate") else None,
    }, indent=2))

    print("== 4) Record usage ==")
    from app.db import GetDB, crud
    used = _accounting_until(int(ONE_GIB * 0.95))
    from app.jobs.review_users import review
    review()
    with GetDB() as db:
        u = crud.get_user(db, USERNAME)
        used = int(u.used_traffic or 0)
    print(f"used_traffic={used} ({used/1024**3:.3f} GiB)")

    print("== 5) Enforce limit (review job) ==")
    from app.jobs.review_users import review
    review()

    from app.db import GetDB, crud
    with GetDB() as db:
        u = crud.get_user(db, USERNAME)
        status = str(u.status)
        limit = int(u.data_limit or 0)
        used = int(u.used_traffic or 0)

    print("== 6) Peer state on node ==")
    _sync_wg()
    from app import xray
    from app.wireguard.transport import client_for_node
    node = xray.nodes.get(NODE_ID)
    transfer = {}
    if node and node.connected:
        c = client_for_node(node)
        if c:
            transfer = c.transfer("wg0") or {}

    limited_ok = "limited" in status.lower()
    strict_cap_ok = used <= limit
    peer_removed = not transfer

    print("== 7) Recharge (reset) — user must stay, peer restored ==")
    r = requests.post(f"{PANEL}/api/user/{USERNAME}/reset", headers=_headers(tok), timeout=30)
    r.raise_for_status()
    reset_body = r.json()
    _sync_wg()
    from app.xray import operations as xray_ops
    with GetDB() as db:
        u = crud.get_user(db, USERNAME)
        xray_ops.connect_node(NODE_ID)
        xray_ops.update_user(u)
    time.sleep(2)
    _sync_wg()

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username="root", password=SSH_PASS, timeout=20)
    try:
        _, stdout, _ = ssh.exec_command("docker exec nexusnode wg show wg0")
        peer_after = stdout.read().decode()
    finally:
        ssh.close()

    recharge_ok = (
        reset_body.get("status") == "active"
        and int(reset_body.get("used_traffic") or 0) == 0
        and "peer:" in peer_after
        and "allowed ips: 10.10.0.2" in peer_after
    )

    report = {
        "username": USERNAME,
        "data_limit": limit,
        "used_traffic": used,
        "status": status,
        "used_gib": round(used / 1024**3, 3),
        "node_transfer": transfer,
        "peer_removed_on_limit": peer_removed,
        "xfer": {k: xfer.get(k) for k in ("external_ok", "bytes", "elapsed_s", "panel_ip")},
        "strict_cap_ok": strict_cap_ok,
        "limited_ok": limited_ok,
        "recharge": {
            "status": reset_body.get("status"),
            "used_traffic": reset_body.get("used_traffic"),
            "peer_restored": recharge_ok,
        },
        "verdict": "PASS" if (limited_ok and strict_cap_ok and peer_removed and recharge_ok) else "FAIL",
    }
    print(json.dumps(report, indent=2, default=str))
    sys.exit(0 if report["verdict"] == "PASS" else 1)


def shutil_which(cmd: str) -> bool:
    import shutil
    return shutil.which(cmd) is not None


if __name__ == "__main__":
    main()
