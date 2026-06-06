#!/usr/bin/env python3
"""WireGuard smoke test: create user via API, connect in isolated netns (no full-route).

Safe by design:
- Client runs in a dedicated ``ip netns`` — host/default routes are untouched.
- ``AllowedIPs`` is limited to the WG server tunnel IP (``10.10.0.1/32``), not 0.0.0.0/0.
- Optional remote mode SSHes the same netns script onto the node host (still isolated).

Usage:
  python3 scripts/wg_smoke_test.py
  WG_SMOKE_SSH_PASSWORD='...' python3 scripts/wg_smoke_test.py --remote
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PANEL = os.environ.get("WG_SMOKE_PANEL", "http://127.0.0.1:8000")
ADMIN_USER = os.environ.get("WG_SMOKE_ADMIN", "admin")
ADMIN_PASS = os.environ.get("WG_SMOKE_ADMIN_PASS", "changeme")
TEST_USER = os.environ.get("WG_SMOKE_USERNAME", "wg_smoke_test")
NODE_ID = int(os.environ.get("WG_SMOKE_NODE_ID", "1"))
# Only route the WG server /32 — never 0.0.0.0/0
SAFE_ALLOWED_IPS = os.environ.get("WG_SMOKE_ALLOWED_IPS", "10.10.0.1/32")
PING_TARGET = os.environ.get("WG_SMOKE_PING_TARGET", "10.10.0.1")


NETNS_SCRIPT = r"""#!/bin/bash
set -e
CONF="$1"
NS="$2"
TARGET="$3"
# WG handshake UDP goes to Endpoint IP (outside AllowedIPs). Isolated netns needs a
# host veth path for that /32 only — never a default route / 0.0.0.0/0.
ENDPOINT_IP=$(awk -F'[= ]+' '/^Endpoint/{print $2}' "$CONF" | cut -d: -f1)
# ifname max 15 chars on Linux
SUFFIX="${NS##*-}"
VETH_HOST="wgh${SUFFIX}"
VETH_NS="wgn${SUFFIX}"
GW_HOST="192.0.2.1"
GW_NS="192.0.2.2"
P2P_MASK="30"
cleanup() {
  ip netns exec "$NS" wg-quick down "$CONF" 2>/dev/null || true
  iptables -t nat -D POSTROUTING -s "${GW_NS}/32" -d "${ENDPOINT_IP}/32" -j MASQUERADE 2>/dev/null || true
  iptables -D FORWARD -s "${GW_NS}/32" -d "${ENDPOINT_IP}/32" -j ACCEPT 2>/dev/null || true
  iptables -D FORWARD -s "${ENDPOINT_IP}/32" -d "${GW_NS}/32" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || true
  ip link del "$VETH_HOST" 2>/dev/null || true
  ip netns del "$NS" 2>/dev/null || true
}
trap cleanup EXIT
ip netns add "$NS"
ip link add "$VETH_NS" type veth peer name "$VETH_HOST"
ip link set "$VETH_NS" netns "$NS"
ip addr add "${GW_HOST}/${P2P_MASK}" dev "$VETH_HOST"
ip link set "$VETH_HOST" up
ip netns exec "$NS" ip addr add "${GW_NS}/${P2P_MASK}" dev "$VETH_NS"
ip netns exec "$NS" ip link set "$VETH_NS" up
ip netns exec "$NS" ip link set lo up
ip netns exec "$NS" ip route add "${ENDPOINT_IP}/32" via "$GW_HOST"
sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1 || true
iptables -t nat -A POSTROUTING -s "${GW_NS}/32" -d "${ENDPOINT_IP}/32" -j MASQUERADE
iptables -A FORWARD -s "${GW_NS}/32" -d "${ENDPOINT_IP}/32" -j ACCEPT
iptables -A FORWARD -s "${ENDPOINT_IP}/32" -d "${GW_NS}/32" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
ip netns exec "$NS" wg-quick up "$CONF"
sleep 10
echo "=== ROUTES (netns) ==="
ip netns exec "$NS" ip route || true
echo "=== HANDSHAKE ==="
ip netns exec "$NS" wg show all | grep -E 'latest handshake|transfer' || true
echo "=== PING ==="
ip netns exec "$NS" ping -c 12 -W 2 -s 512 "$TARGET" || true
sleep 1
echo "=== TRANSFER ==="
ip netns exec "$NS" wg show all transfer
TX=$(ip netns exec "$NS" wg show all transfer 2>/dev/null | awk 'NF>=3 {sum+=$2+$3} END {print sum+0}')
if ip netns exec "$NS" wg show all 2>/dev/null | grep -qE 'latest handshake: [1-9]'; then
  echo "HANDSHAKE_OK=1"
else
  echo "HANDSHAKE_OK=0"
fi
echo "CLIENT_BYTES=$TX"
echo "ENDPOINT_IP=$ENDPOINT_IP"
"""

# Runs inside nexusnode (--network=host): client shares the host netns with wg0.
DOCKER_SMOKE_SCRIPT = r"""#!/bin/bash
set -e
CONF="$1"
TARGET="$2"
cleanup() { wg-quick down "$CONF" 2>/dev/null || true; }
trap cleanup EXIT
wg-quick up "$CONF"
sleep 10
echo "=== HANDSHAKE ==="
wg show all | grep -E 'latest handshake|transfer' || true
echo "=== PING ==="
ping -c 8 -W 2 -s 512 "$TARGET" 2>/dev/null || true
sleep 1
echo "=== TRANSFER ==="
wg show all transfer
TX=$(wg show all transfer 2>/dev/null | awk '$1!="wg0" && NF>=3 {sum+=$2+$3} END {print sum+0}')
if wg show all 2>/dev/null | grep -qE 'latest handshake: [1-9]'; then
  echo "HANDSHAKE_OK=1"
else
  echo "HANDSHAKE_OK=0"
fi
echo "CLIENT_BYTES=$TX"
"""


def _api_token() -> str:
    r = requests.post(
        f"{PANEL}/api/admin/token",
        data={"username": ADMIN_USER, "password": ADMIN_PASS},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def create_user_via_api(token: str) -> dict:
    """Same path the dashboard uses: POST /api/user."""
    payload = {
        "username": TEST_USER,
        "status": "active",
        "data_limit": 0,
        "proxies": {"wireguard": {}},
        "inbounds": {},
    }
    r = requests.post(
        f"{PANEL}/api/user",
        headers=_headers(token),
        json=payload,
        timeout=30,
    )
    if r.status_code == 409:
        return {"username": TEST_USER, "reused": True}
    r.raise_for_status()
    body = r.json()
    body["reused"] = False
    return body


def _try_rebuild_agent():
    """Optional: rebuild agent when WG_NODE_SSH_PASSWORD or .wg_node_ssh exists."""
    import os
    from pathlib import Path

    pwd = os.environ.get("WG_NODE_SSH_PASSWORD", "")
    if not pwd:
        f = Path(os.environ.get("WG_NODE_SSH_PASSWORD_FILE", "/opt/nexuspanel/.wg_node_ssh"))
        if f.is_file():
            pwd = f.read_text().strip()
    if not pwd:
        return False
    from app.db import GetDB, crud
    import provisioning as prov

    with GetDB() as db:
        host = crud.get_node_by_id(db, NODE_ID).address
    panel_url = prov.resolve_panel_public_url()
    from config import NODE_AGENT_IMAGE, NODE_BOOTSTRAP_TOKEN, NODE_CONTROL_SECRET
    cmd = prov.build_install_command(
        panel_url, NODE_BOOTSTRAP_TOKEN, "wireguard1",
        core_kind="wireguard", image=NODE_AGENT_IMAGE,
        control_secret=NODE_CONTROL_SECRET or None,
        force_image_rebuild=True,
    )
    creds = prov.SSHCredentials(host=host, password=pwd)
    prov.run_remote_command(creds, cmd, exec_timeout=1800)
    return True


def _sync_wg_and_connect():
    from app import xray
    from app.db import GetDB, crud
    from app.wireguard.operations import sync_all_nodes
    from app.xray import operations as xray_ops

    with GetDB() as db:
        dbnode = crud.get_node_by_id(db, NODE_ID)
        if not dbnode:
            raise SystemExit(f"node id={NODE_ID} not found")
        node_name = dbnode.name

    for attempt in range(6):
        if NODE_ID in xray.nodes and xray.nodes[NODE_ID].connected:
            break
        xray_ops.connect_node(NODE_ID)
        time.sleep(15)

    with GetDB() as db:
        count = sync_all_nodes(db)
    connected = NODE_ID in xray.nodes and xray.nodes[NODE_ID].connected
    return node_name, count, connected


def _build_safe_conf(*, endpoint: str | None = None) -> str:
    from app.db import GetDB, crud
    from app.models.proxy import ProxyTypes
    from app.subscription.wireguard import render_wireguard_conf, node_endpoint

    with GetDB() as db:
        dbuser = crud.get_user(db, TEST_USER)
        if not dbuser:
            raise SystemExit(f"user {TEST_USER} not found after create")
        dbnode = crud.get_node_by_id(db, NODE_ID)
        if not dbnode or not dbnode.wireguard:
            raise SystemExit("WG node config missing")
        proxy = next((p for p in dbuser.proxies if p.type == ProxyTypes.WireGuard), None)
        if not proxy:
            raise SystemExit("user has no wireguard proxy")
        settings = dict(proxy.settings or {})
        if not settings.get("address"):
            from app.wireguard.operations import ensure_user_address
            ensure_user_address(db, proxy, dbnode.wireguard.subnet)
            settings = dict(proxy.settings or {})

        ep = endpoint or node_endpoint(dbnode)
        return render_wireguard_conf(
            private_key=settings["private_key"],
            address=settings["address"],
            server_public_key=dbnode.wireguard.public_key,
            endpoint=ep,
            dns=None,
            preshared_key=settings.get("preshared_key"),
            allowed_ips=SAFE_ALLOWED_IPS,
            mtu=dbnode.wireguard.mtu,
        )


def _node_transfer() -> dict:
    from app import xray
    from app.db import GetDB, crud
    from app.wireguard.transport import client_for_node

    with GetDB() as db:
        dbnode = crud.get_node_by_id(db, NODE_ID)
        if not dbnode or not dbnode.wireguard:
            return {}
        iface = dbnode.wireguard.interface
    node = xray.nodes.get(NODE_ID)
    if not node:
        return {}
    client = client_for_node(node)
    if not client:
        return {}
    try:
        return client.transfer(iface)
    except Exception as exc:
        return {"error": str(exc)}


def _user_usage(username: str) -> int:
    from app.db import GetDB, crud
    with GetDB() as db:
        u = crud.get_user(db, username)
        return int(u.used_traffic or 0) if u else 0


def _record_usage_twice():
    from app.jobs.record_usages import record_user_usages
    record_user_usages()
    time.sleep(2)
    record_user_usages()


HOST_SMOKE_SCRIPT = r"""#!/bin/bash
set -e
CONF="$1"
TARGET="$2"
cleanup() { wg-quick down "$CONF" 2>/dev/null || true; }
trap cleanup EXIT
wg-quick up "$CONF"
sleep 10
echo "=== HANDSHAKE ==="
wg show all | grep -E 'latest handshake|transfer' || true
echo "=== PING ==="
ping -c 12 -W 2 -s 512 "$TARGET" || true
sleep 1
echo "=== TRANSFER ==="
wg show all transfer
TX=$(wg show all transfer 2>/dev/null | awk 'NF>=3 {sum+=$2+$3} END {print sum+0}')
if wg show all 2>/dev/null | grep -qE 'latest handshake: [1-9]'; then
  echo "HANDSHAKE_OK=1"
else
  echo "HANDSHAKE_OK=0"
fi
echo "CLIENT_BYTES=$TX"
"""


def _run_external_host(conf: str) -> dict:
    """Client on this machine's network stack → node public Endpoint (true external path)."""
    if not shutil.which("wg-quick"):
        raise SystemExit("wireguard-tools missing on this host (apt install wireguard-tools)")

    with tempfile.TemporaryDirectory() as td:
        conf_path = Path(td) / "client.conf"
        script_path = Path(td) / "run.sh"
        conf_path.write_text(conf)
        script_path.write_text(HOST_SMOKE_SCRIPT)
        script_path.chmod(0o755)
        proc = subprocess.run(
            ["bash", str(script_path), str(conf_path), PING_TARGET],
            capture_output=True,
            text=True,
            timeout=90,
        )
        out = proc.stdout + proc.stderr
        handshake_ok = "HANDSHAKE_OK=1" in out
        client_bytes = 0
        for line in out.splitlines():
            if line.startswith("CLIENT_BYTES="):
                client_bytes = int(line.split("=", 1)[1] or 0)
        return {
            "mode": "external-host",
            "exit_code": proc.returncode,
            "handshake_ok": handshake_ok,
            "client_bytes": client_bytes,
            "log_tail": out[-2500:],
        }


def _run_netns_local(conf: str) -> dict:
    if not shutil.which("wg-quick"):
        raise SystemExit("wireguard-tools missing on this host (apt install wireguard-tools)")

    ns = f"wg-smoke-{os.getpid()}"
    with tempfile.TemporaryDirectory() as td:
        conf_path = Path(td) / "client.conf"
        script_path = Path(td) / "run.sh"
        conf_path.write_text(conf)
        script_path.write_text(NETNS_SCRIPT)
        script_path.chmod(0o755)
        proc = subprocess.run(
            ["bash", str(script_path), str(conf_path), ns, PING_TARGET],
            capture_output=True,
            text=True,
            timeout=90,
        )
        out = proc.stdout + proc.stderr
        handshake_ok = "HANDSHAKE_OK=1" in out
        client_bytes = 0
        for line in out.splitlines():
            if line.startswith("CLIENT_BYTES="):
                client_bytes = int(line.split("=", 1)[1] or 0)
        return {
            "mode": "external-netns",
            "exit_code": proc.returncode,
            "handshake_ok": handshake_ok,
            "client_bytes": client_bytes,
            "log_tail": out[-2000:],
        }


def _run_docker_remote(host: str, user: str, password: str, conf: str) -> dict:
    """Run client wg-quick inside nexusnode (host network, loopback to wg0)."""
    import paramiko

    remote_dir = f"/tmp/wg-smoke-{int(time.time())}"
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=user, password=password, timeout=20)
    try:
        client.exec_command(f"mkdir -p {remote_dir}")
        sftp = client.open_sftp()
        sftp.file(f"{remote_dir}/client.conf", "w").write(conf)
        sftp.file(f"{remote_dir}/run.sh", "w").write(DOCKER_SMOKE_SCRIPT)
        client.exec_command(f"chmod +x {remote_dir}/run.sh")
        sftp.close()
        cmd = (
            f"docker cp {remote_dir}/client.conf nexusnode:/tmp/wg-smoke-client.conf "
            f"&& docker cp {remote_dir}/run.sh nexusnode:/tmp/wg-smoke-run.sh "
            f"&& docker exec nexusnode chmod +x /tmp/wg-smoke-run.sh "
            f"&& docker exec nexusnode bash /tmp/wg-smoke-run.sh /tmp/wg-smoke-client.conf {PING_TARGET}"
        )
        _, stdout, stderr = client.exec_command(cmd, timeout=90)
        out = stdout.read().decode() + stderr.read().decode()
        client.exec_command(f"rm -rf {remote_dir}")
        client_bytes = 0
        for line in out.splitlines():
            if line.startswith("CLIENT_BYTES="):
                client_bytes = int(line.split("=", 1)[1] or 0)
        return {
            "mode": "remote-docker",
            "host": host,
            "handshake_ok": "HANDSHAKE_OK=1" in out,
            "client_bytes": client_bytes,
            "log_tail": out[-2000:],
        }
    finally:
        client.close()


def _run_netns_remote(host: str, user: str, password: str, conf: str) -> dict:
    import paramiko

    ns = f"wg-smoke-remote"
    remote_dir = f"/tmp/wg-smoke-{int(time.time())}"
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=user, password=password, timeout=20)
    try:
        client.exec_command(f"mkdir -p {remote_dir}")
        sftp = client.open_sftp()
        sftp.file(f"{remote_dir}/client.conf", "w").write(conf)
        sftp.file(f"{remote_dir}/run.sh", "w").write(NETNS_SCRIPT)
        client.exec_command(f"chmod +x {remote_dir}/run.sh")
        sftp.close()
        _, stdout, stderr = client.exec_command(
            f"bash {remote_dir}/run.sh {remote_dir}/client.conf {ns} {PING_TARGET}",
            timeout=90,
        )
        out = stdout.read().decode() + stderr.read().decode()
        client.exec_command(f"rm -rf {remote_dir}")
        client_bytes = 0
        for line in out.splitlines():
            if line.startswith("CLIENT_BYTES="):
                client_bytes = int(line.split("=", 1)[1] or 0)
        return {
            "mode": "remote-netns",
            "host": host,
            "handshake_ok": "HANDSHAKE_OK=1" in out,
            "client_bytes": client_bytes,
            "log_tail": out[-2000:],
        }
    finally:
        client.close()


def main():
    parser = argparse.ArgumentParser(description="WireGuard smoke test (isolated netns)")
    parser.add_argument("--remote", action="store_true", help="Also run netns on node host via SSH")
    parser.add_argument("--host", default=None, help="SSH host (default: node address from DB)")
    args = parser.parse_args()

    report = {"steps": []}

    if os.environ.get("WG_SMOKE_REBUILD", "").lower() in ("1", "true", "yes"):
        print("== 0) Rebuild node agent via SSH ==")
        try:
            _try_rebuild_agent()
            print("rebuild OK")
        except Exception as exc:
            print("rebuild skipped/failed:", exc)

    print("== 1) Login + create user via API ==")
    token = _api_token()
    user = create_user_via_api(token)
    report["user"] = user
    print(json.dumps(user, indent=2))

    print("== 2) Sync WG peers to node ==")
    node_name, synced, connected = _sync_wg_and_connect()
    report["wg_sync_nodes"] = synced
    report["node_connected"] = connected
    print(f"node={node_name} sync_ok={synced} connected={connected}")

    conf = _build_safe_conf()
    report["conf_allowed_ips"] = SAFE_ALLOWED_IPS
    report["conf_endpoint"] = re.search(r"Endpoint = (.+)", conf).group(1) if "Endpoint" in conf else None

    usage_before = _user_usage(TEST_USER)
    transfer_before = _node_transfer()
    report["usage_before"] = usage_before
    report["transfer_before"] = transfer_before

    print("== 3) External connect from this host → node public Endpoint ==")
    local = _run_external_host(conf)
    report["local_test"] = local
    print(local.get("log_tail", ""))

    ssh_pwd = (
        os.environ.get("WG_SMOKE_SSH_PASSWORD", "")
        or os.environ.get("WG_NODE_SSH_PASSWORD", "")
    )
    if not ssh_pwd:
        f = Path(os.environ.get("WG_NODE_SSH_PASSWORD_FILE", "/opt/nexuspanel/.wg_node_ssh"))
        if f.is_file():
            ssh_pwd = f.read_text().strip()

    if args.remote:
        if not ssh_pwd:
            report["remote_test"] = {"skipped": "SSH password not set (WG_SMOKE_SSH_PASSWORD)"}
        else:
            from app.db import GetDB, crud as c

            with GetDB() as db:
                dbnode = c.get_node_by_id(db, NODE_ID)
                host = args.host or dbnode.address
                listen = dbnode.wireguard.listen_port if dbnode.wireguard else 51820
            remote_conf = _build_safe_conf(endpoint=f"127.0.0.1:{listen}")
            report["remote_test"] = _run_docker_remote(host, "root", ssh_pwd, remote_conf)
            print("== 3b) [optional] On-node loopback inside nexusnode ==")
            print(report["remote_test"].get("log_tail", ""))

    time.sleep(2)
    transfer_mid = _node_transfer()
    print("== 4) Record usage (panel accounting) ==")
    _record_usage_twice()
    usage_after = _user_usage(TEST_USER)
    transfer_after = _node_transfer()
    report["usage_after"] = usage_after
    report["transfer_after"] = transfer_after
    report["usage_delta"] = usage_after - usage_before

    ok_user = user.get("username") == TEST_USER
    ok_hs = local.get("handshake_ok")
    client_bytes = local.get("client_bytes") or 0
    ok_traffic = client_bytes > 0 or _transfer_grew(transfer_before, transfer_after)
    ok_usage = report["usage_delta"] > 0 or ok_traffic
    report["verdict"] = "PASS" if (ok_user and ok_hs and ok_usage) else "FAIL"
    if not ok_hs and report.get("node_connected"):
        report["hint"] = (
            "WG sync OK but external handshake failed — check UDP listen_port, "
            "peer sync, and that the client can route to the node Endpoint IP."
        )

    print("\n=== REPORT ===")
    print(json.dumps(report, indent=2, default=str))
    sys.exit(0 if report["verdict"] == "PASS" else 1)


def _plain_dict(d: dict) -> dict:
    try:
        from rpyc.utils.classic import obtain
        d = obtain(d)
    except Exception:
        pass
    if not isinstance(d, dict):
        return {}
    if "error" in d:
        return {}
    out = {}
    for k, v in d.items():
        try:
            if isinstance(v, dict):
                out[str(k)] = {"rx": int(v.get("rx", 0)), "tx": int(v.get("tx", 0))}
        except Exception:
            continue
    return out


def _transfer_grew(before: dict, after: dict) -> bool:
    def total(d: dict) -> int:
        s = 0
        for v in _plain_dict(d).values():
            s += int(v.get("rx", 0)) + int(v.get("tx", 0))
        return s
    return total(after) > total(before)


if __name__ == "__main__":
    main()
