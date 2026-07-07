#!/usr/bin/env python3
"""Apply host NAT/FORWARD rules for WG subnets on a node (SSH)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.provisioning import run_remote_command
from app.provisioning.node_ssh import resolve_node_ssh

HOST_EGRESS = r"""
set -e
sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1 || true
grep -q '^net.ipv4.ip_forward=1' /etc/sysctl.conf 2>/dev/null || echo 'net.ipv4.ip_forward=1' >> /etc/sysctl.conf
cat > /usr/local/bin/nexuspanel-wg-egress.sh << 'NPEOF'
#!/bin/bash
set -e
sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1 || true
WG_OUT=$(ip route get 8.8.8.8 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="dev") print $(i+1)}')
[ -n "$WG_OUT" ] || exit 0
for SUB in 10.10.0.0/24 10.11.0.0/24; do
  iptables -t nat -C POSTROUTING -s "$SUB" -o "$WG_OUT" -j MASQUERADE 2>/dev/null \
    || iptables -t nat -A POSTROUTING -s "$SUB" -o "$WG_OUT" -j MASQUERADE
done
for IF in wg0 wg1; do
  ip link show "$IF" >/dev/null 2>&1 || continue
  iptables -C FORWARD -i "$IF" -j ACCEPT 2>/dev/null || iptables -A FORWARD -i "$IF" -j ACCEPT
  iptables -C FORWARD -o "$IF" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null \
    || iptables -A FORWARD -o "$IF" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
done
NPEOF
chmod +x /usr/local/bin/nexuspanel-wg-egress.sh
/usr/local/bin/nexuspanel-wg-egress.sh
CRON_LINE='@reboot root /usr/local/bin/nexuspanel-wg-egress.sh'
grep -qF 'nexuspanel-wg-egress.sh' /etc/crontab 2>/dev/null || echo "$CRON_LINE" >> /etc/crontab
echo "egress OK via $(ip route get 8.8.8.8 | awk '{for(i=1;i<=NF;i++) if($i==\"dev\") print $(i+1)}')"
iptables -t nat -S POSTROUTING | grep -E '10\.10|10\.11' || true
"""


def main() -> int:
    import os

    host = os.environ.get("WG_NODE_HOST", "")
    if not host:
        from app.db import GetDB, crud
        with GetDB() as db:
            nodes = crud.get_wireguard_nodes(db)
            host = nodes[0].address if nodes else ""
    if not host:
        print("Set WG_NODE_HOST or configure a WireGuard node in the panel", file=sys.stderr)
        return 2
    creds = resolve_node_ssh(host)
    print(run_remote_command(creds, HOST_EGRESS, exec_timeout=60))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
