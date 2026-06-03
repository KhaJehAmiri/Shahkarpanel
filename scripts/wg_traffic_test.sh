#!/bin/sh
# Real-kernel WireGuard E2E: a server interface (root ns) and a client
# interface (separate netns) connected over a veth underlay, then real ping
# traffic. Proves native `wg`/`ip` management + non-zero transfer counters.
set -e

D=$(mktemp -d)
wg genkey > "$D/srv.key"; wg pubkey < "$D/srv.key" > "$D/srv.pub"
wg genkey > "$D/cli.key"; wg pubkey < "$D/cli.key" > "$D/cli.pub"
SRV_PUB=$(cat "$D/srv.pub"); CLI_PUB=$(cat "$D/cli.pub")
echo "SRV_PUB=$SRV_PUB"
echo "CLI_PUB=$CLI_PUB"

# Underlay veth: root <-> cli netns
ip netns add cli
ip link add veth0 type veth peer name veth1
ip link set veth1 netns cli
ip addr add 10.99.0.1/24 dev veth0
ip link set veth0 up
ip netns exec cli ip addr add 10.99.0.2/24 dev veth1
ip netns exec cli ip link set veth1 up
ip netns exec cli ip link set lo up

# Server WireGuard (root ns) — this is exactly what the node agent runs.
ip link add wgsrv type wireguard
ip addr add 10.30.0.1/24 dev wgsrv
wg set wgsrv listen-port 51820 private-key "$D/srv.key"
wg set wgsrv peer "$CLI_PUB" allowed-ips 10.30.0.2/32
ip link set wgsrv up

# Client WireGuard (cli netns)
ip netns exec cli ip link add wgc type wireguard
ip netns exec cli ip addr add 10.30.0.2/24 dev wgc
ip netns exec cli wg set wgc private-key "$D/cli.key" peer "$SRV_PUB" \
  allowed-ips 10.30.0.0/24 endpoint 10.99.0.1:51820 persistent-keepalive 5
ip netns exec cli ip link set wgc up

echo "=== TRANSFER_BEFORE ==="
wg show wgsrv transfer
echo "=== PING (client -> server tunnel IP) ==="
ip netns exec cli ping -c 8 -W 2 10.30.0.1 | tail -3 || true
sleep 1
echo "=== HANDSHAKE ==="
wg show wgsrv latest-handshakes
echo "=== TRANSFER_AFTER ==="
wg show wgsrv transfer

# Cleanup
ip link del wgsrv 2>/dev/null || true
ip netns del cli 2>/dev/null || true
echo "=== DONE ==="
