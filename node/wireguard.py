"""Native WireGuard interface management for a NexusPanel node (Phase 11.2).

The panel pushes a declarative spec (interface keys, listen port, address and
the full peer list) and reads back per-peer transfer counters. Those counters
are mapped ``public_key -> User.id`` on the panel and folded into the single
``User.used_traffic`` — see ``docs/accounting-contract.md``.

The module is deliberately self-contained (stdlib only) and the command runner
is injectable so the config rendering and ``wg show transfer`` parsing are unit
testable without root or a real WireGuard interface.
"""
import ipaddress
import logging
import os
import shutil
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterator, List, Optional, Sequence

logger = logging.getLogger("nexus-node-wg")


@contextmanager
def ephemeral_psk_file(psk: str) -> Iterator[str]:
    """Write a PSK to a short-lived temp file readable only by this process (L4)."""
    fd, path = tempfile.mkstemp(prefix="nexus-wg-psk-", suffix=".key")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(psk.strip() + "\n")
        os.chmod(path, 0o600)
        yield path
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


@dataclass
class WireGuardPeer:
    public_key: str
    allowed_ips: List[str]
    preshared_key: Optional[str] = None


@dataclass
class WireGuardSpec:
    interface: str
    listen_port: int
    private_key: str
    address: List[str]                      # interface CIDRs, e.g. ["10.10.0.1/24"]
    peers: List[WireGuardPeer] = field(default_factory=list)
    mtu: Optional[int] = None
    # AmneziaWG obfuscation params (Jc/Jmin/...). When set and amneziawg-go is
    # installed, the manager uses awg syncconf instead of plain wg.
    amnezia: Optional[dict] = None

    @classmethod
    def from_dict(cls, data: dict) -> "WireGuardSpec":
        peers = [
            WireGuardPeer(
                public_key=p["public_key"],
                allowed_ips=list(p.get("allowed_ips") or []),
                preshared_key=p.get("preshared_key") or None,
            )
            for p in (data.get("peers") or [])
        ]
        address = data.get("address")
        if isinstance(address, str):
            address = [address]
        return cls(
            interface=data["interface"],
            listen_port=int(data["listen_port"]),
            private_key=data["private_key"],
            address=list(address or []),
            peers=peers,
            mtu=int(data["mtu"]) if data.get("mtu") else None,
            amnezia=data.get("amnezia") or None,
        )


def parse_transfer(output: str) -> Dict[str, dict]:
    """Parse ``wg show <iface> transfer`` output.

    Each line is ``<public_key>\\t<rx_bytes>\\t<tx_bytes>``. Returns a map of
    ``public_key -> {"rx": int, "tx": int}``.
    """
    result: Dict[str, dict] = {}
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t") if "\t" in line else line.split()
        if len(parts) < 3:
            continue
        public_key, rx, tx = parts[0], parts[1], parts[2]
        try:
            result[public_key] = {"rx": int(rx), "tx": int(tx)}
        except ValueError:
            continue
    return result


def render_syncconf(spec: WireGuardSpec, *, include_amnezia: Optional[bool] = None) -> str:
    """Render the stripped config consumed by ``wg``/``awg syncconf``.

    Interface key/port plus peers; addresses and MTU are applied via ``ip``
    separately. AmneziaWG params are only included when the server runs AWG.
    """
    show_awg = include_amnezia if include_amnezia is not None else bool(spec.amnezia)
    lines = [
        "[Interface]",
        f"ListenPort = {spec.listen_port}",
        f"PrivateKey = {spec.private_key}",
    ]
    if show_awg and spec.amnezia:
        for key in ("Jc", "Jmin", "Jmax", "S1", "S2", "S3", "S4", "H1", "H2", "H3", "H4"):
            if key in spec.amnezia:
                lines.append(f"{key} = {spec.amnezia[key]}")
    for peer in spec.peers:
        lines.append("")
        lines.append("[Peer]")
        lines.append(f"PublicKey = {peer.public_key}")
        if peer.preshared_key:
            lines.append(f"PresharedKey = {peer.preshared_key}")
        allowed = ", ".join(peer.allowed_ips) if peer.allowed_ips else ""
        lines.append(f"AllowedIPs = {allowed}")
    return "\n".join(lines) + "\n"


def subnets_from_specs(specs: Sequence[WireGuardSpec]) -> List[str]:
    """Derive client NAT subnets (e.g. 10.10.0.0/24) from interface addresses."""
    subnets: List[str] = []
    seen: set[str] = set()
    for spec in specs:
        for addr in spec.address:
            try:
                net = str(ipaddress.ip_network(addr, strict=False))
            except ValueError:
                continue
            if net not in seen:
                seen.add(net)
                subnets.append(net)
    return subnets


def ensure_udp_input_ports(
    ports: Sequence[int],
    run: Optional[Callable] = None,
) -> None:
    """Open UDP listen ports on the host firewall (iptables INPUT + ufw).

    Idempotent. Safe to call on every sync when a WG / Xray-native port changes —
    operators should not need to touch the firewall by hand.
    """
    runner = run or WireGuardManager._default_run
    wanted = sorted({int(p) for p in ports if p and 0 < int(p) < 65536})
    if not wanted:
        return

    if shutil.which("iptables"):
        for port in wanted:
            check = [
                "iptables", "-C", "INPUT", "-p", "udp", "--dport", str(port), "-j", "ACCEPT",
            ]
            add = [
                "iptables", "-I", "INPUT", "-p", "udp", "--dport", str(port), "-j", "ACCEPT",
            ]
            if getattr(runner(check, check=False), "returncode", 1) != 0:
                runner(add, check=False)

    if shutil.which("ufw"):
        # Never prompt; skip when ufw is inactive to avoid hanging sync.
        status = runner(["ufw", "status"], check=False)
        status_out = (getattr(status, "stdout", "") or "").lower()
        if "status: active" in status_out:
            for port in wanted:
                runner(
                    [
                        "ufw",
                        "--force",
                        "allow",
                        f"{port}/udp",
                        "comment",
                        "nexuspanel-wg",
                    ],
                    check=False,
                )

    if shutil.which("firewall-cmd"):
        state = runner(["firewall-cmd", "--state"], check=False)
        if getattr(state, "returncode", 1) == 0 and "running" in (
            getattr(state, "stdout", "") or ""
        ).lower():
            for port in wanted:
                runner(
                    ["firewall-cmd", "--permanent", f"--add-port={port}/udp"],
                    check=False,
                )
            runner(["firewall-cmd", "--reload"], check=False)


def ensure_egress_forwarding(
    specs: Sequence[WireGuardSpec],
    run: Optional[Callable] = None,
) -> None:
    """MASQUERADE + FORWARD so WG clients can reach the internet on host network.

    Idempotent: skips rules that already exist. No-op when iptables or the
    default route is unavailable (unit tests / minimal containers).
    """
    if not shutil.which("iptables"):
        return
    runner = run or WireGuardManager._default_run
    route = runner(["ip", "route", "get", "8.8.8.8"], check=False)
    if getattr(route, "returncode", 1) != 0:
        return
    parts = (getattr(route, "stdout", "") or "").split()
    try:
        dev_idx = parts.index("dev")
        outbound = parts[dev_idx + 1]
    except (ValueError, IndexError):
        return

    subnets = subnets_from_specs(specs)
    interfaces = sorted({spec.interface for spec in specs})

    def _ensure(table: Optional[str], args: List[str]) -> None:
        check = ["iptables"]
        add = ["iptables"]
        if table:
            check.extend(["-t", table])
            add.extend(["-t", table])
        check.extend(["-C", *args])
        add.extend(["-A", *args])
        if getattr(runner(check, check=False), "returncode", 1) != 0:
            runner(add, check=False)

    for subnet in subnets:
        _ensure("nat", ["POSTROUTING", "-s", subnet, "-o", outbound, "-j", "MASQUERADE"])
    for iface in interfaces:
        _ensure(None, ["FORWARD", "-i", iface, "-j", "ACCEPT"])
        _ensure(
            None,
            [
                "FORWARD",
                "-o",
                iface,
                "-m",
                "conntrack",
                "--ctstate",
                "RELATED,ESTABLISHED",
                "-j",
                "ACCEPT",
            ],
        )
    ensure_udp_input_ports([spec.listen_port for spec in specs], run=runner)
    logger.info(
        "Ensured WG egress (ifaces=%s, subnets=%s, out=%s)",
        interfaces,
        subnets,
        outbound,
    )


class WireGuardManager:
    """Thin wrapper over ``wg``/``awg`` + ``ip`` for declarative interface management."""

    def __init__(self, run: Optional[Callable] = None):
        self._run = run or self._default_run
        # pubkey -> (rx, tx, monotonic_ts) for idle-endpoint detection
        self._peer_traffic_snapshots: Dict[str, tuple] = {}
        # Serializes interface-mutating operations (apply/reconcile/flush/
        # teardown). The panel calls these concurrently from independent
        # sources — the ~10s health-check reconcile, the ~300s periodic
        # resync, and ad-hoc syncs triggered by user changes — all against
        # this same shared manager instance. Without a lock, a `syncconf` +
        # `_ensure_spec_peers` (apply) can interleave with a concurrent
        # remove/re-add (reconcile/flush), causing transient peer drops and
        # duplicated `amneziawg-go` teardown/recreate churn. Reentrant so a
        # method that calls another locking method internally (e.g. `apply`
        # -> `ensure_interface` -> `teardown`) doesn't self-deadlock.
        self._lock = threading.RLock()

    @staticmethod
    def _default_run(cmd, input=None, check=True):
        return subprocess.run(
            cmd, input=input, text=True, capture_output=True, check=check
        )

    def available(self) -> bool:
        return shutil.which("wg") is not None and shutil.which("ip") is not None

    def amnezia_available(self) -> bool:
        """True when AWG can be applied (kernel ``awg`` and/or userspace engine)."""
        return shutil.which("ip") is not None and (
            shutil.which("awg") is not None or shutil.which("amneziawg-go") is not None
        )

    def _use_amnezia(self, spec: WireGuardSpec) -> bool:
        return bool(spec.amnezia) and self.amnezia_available()

    def _wg_bin(self, spec: WireGuardSpec) -> str:
        if self._use_amnezia(spec) and shutil.which("awg"):
            return "awg"
        return "wg"

    def _awg_daemon_running(self, interface: str) -> bool:
        """True only when a live ``amneziawg-go <interface>`` process exists."""
        needle = f"amneziawg-go {interface}"
        try:
            for pid in os.listdir("/proc"):
                if not pid.isdigit():
                    continue
                with open(f"/proc/{pid}/status", "r", encoding="utf-8") as fh:
                    status = fh.read()
                if not status.startswith("State:"):
                    continue
                state = status.splitlines()[0].split()[1]
                if state == "Z":
                    continue
                with open(f"/proc/{pid}/cmdline", "rb") as fh:
                    cmd = fh.read().replace(b"\0", b" ").decode(errors="ignore")
                if needle in cmd:
                    return True
        except OSError:
            return False
        return False

    def _interface_is_userspace_awg(self, interface: str) -> bool:
        if self._awg_daemon_running(interface):
            return True
        wg = "awg" if shutil.which("awg") else "wg"
        result = self._run([wg, "show", interface, "listen-port"], check=False)
        if getattr(result, "returncode", 1) != 0:
            return False
        return bool((getattr(result, "stdout", "") or "").strip())

    def interface_exists(self, interface: str) -> bool:
        result = self._run(["ip", "link", "show", interface], check=False)
        return getattr(result, "returncode", 1) == 0

    def ensure_interface(self, spec: WireGuardSpec) -> None:
        want_awg = self._use_amnezia(spec)
        exists = self.interface_exists(spec.interface)
        is_awg = self._interface_is_userspace_awg(spec.interface) if exists else False
        userspace_awg = want_awg and os.path.exists("/dev/net/tun") and shutil.which("amneziawg-go")
        daemon_live = self._awg_daemon_running(spec.interface) if userspace_awg else False

        if userspace_awg and not daemon_live:
            if exists:
                self.teardown(spec.interface)
            self._run(["amneziawg-go", spec.interface], check=False)
            import time
            for _ in range(20):
                if self._awg_daemon_running(spec.interface):
                    break
                time.sleep(0.1)
        elif want_awg and not is_awg and not exists and shutil.which("awg"):
            self._run(["ip", "link", "add", "dev", spec.interface, "type", "wireguard"], check=False)
        elif not want_awg and is_awg:
            self.teardown(spec.interface)
            self._run(["ip", "link", "add", "dev", spec.interface, "type", "wireguard"])
        elif not want_awg and not exists:
            self._run(["ip", "link", "add", "dev", spec.interface, "type", "wireguard"])
        # Make addresses declarative: flush then re-add.
        self._run(["ip", "address", "flush", "dev", spec.interface], check=False)
        for addr in spec.address:
            self._run(["ip", "address", "add", addr, "dev", spec.interface], check=False)
        if spec.mtu:
            self._run(["ip", "link", "set", "mtu", str(spec.mtu), "dev", spec.interface], check=False)
        self._run(["ip", "link", "set", "up", "dev", spec.interface], check=False)

    def apply_specs(self, specs: List[WireGuardSpec]) -> None:
        for spec in specs:
            try:
                self.apply(spec)
            except Exception as exc:
                logger.warning("WireGuard apply for %s failed: %s", spec.interface, exc)
        ensure_egress_forwarding(specs, run=self._run)

    def open_udp_ports(self, ports: Sequence[int]) -> None:
        """Expose UDP ports publicly (used for Xray-native WG + stack ports)."""
        ensure_udp_input_ports(ports, run=self._run)

    def apply_warp_tproxy(
        self,
        *,
        enabled: bool,
        subnets: Sequence[str],
        port: int,
        interfaces: Optional[Sequence[str]] = None,
    ) -> bool:
        from warp_tproxy import apply_warp_tproxy

        return bool(
            apply_warp_tproxy(
                enabled=enabled,
                subnets=subnets,
                port=port,
                interfaces=interfaces,
                run=self._run,
            )
        )

    def _peer_handshakes(self, interface: str) -> dict:
        """Return ``public_key -> unix_timestamp`` from ``awg/wg show … handshakes``."""
        wg = "awg" if self._interface_is_userspace_awg(interface) or shutil.which("awg") else "wg"
        result = self._run([wg, "show", interface, "latest-handshakes"], check=False)
        if getattr(result, "returncode", 1) != 0:
            return {}
        out: dict = {}
        for line in (getattr(result, "stdout", "") or "").splitlines():
            parts = line.split()
            if len(parts) != 2:
                continue
            try:
                out[parts[0]] = int(parts[1])
            except ValueError:
                continue
        return out

    def _peer_endpoints(self, interface: str) -> dict:
        """Return ``public_key -> endpoint`` from ``awg/wg show … endpoints``."""
        wg = "awg" if self._interface_is_userspace_awg(interface) or shutil.which("awg") else "wg"
        result = self._run([wg, "show", interface, "endpoints"], check=False)
        if getattr(result, "returncode", 1) != 0:
            return {}
        out: dict = {}
        for line in (getattr(result, "stdout", "") or "").splitlines():
            parts = line.split()
            if len(parts) != 2:
                continue
            out[parts[0]] = parts[1]
        return out

    def _peer_dump_rows(self, interface: str) -> dict:
        """Return ``public_key -> {psk, allowed_ips}`` from ``wg show … dump``."""
        wg = "awg" if self._interface_is_userspace_awg(interface) or shutil.which("awg") else "wg"
        result = self._run([wg, "show", interface, "dump"], check=False)
        if getattr(result, "returncode", 1) != 0:
            return {}
        out: dict = {}
        for line in (getattr(result, "stdout", "") or "").splitlines():
            parts = line.split("\t")
            if len(parts) < 4:
                continue
            pubkey, psk, _endpoint, allowed = parts[0], parts[1], parts[2], parts[3]
            out[pubkey] = {
                "preshared_key": None if psk == "(none)" else psk,
                "allowed_ips": allowed,
            }
        return out

    def _add_peer(self, wg: str, interface: str, pubkey: str, row: dict) -> bool:
        """Add or update a peer via ``awg/wg set`` (PSK via temp file)."""
        cmd = [wg, "set", interface, "peer", pubkey, "allowed-ips", row["allowed_ips"]]
        psk = row.get("preshared_key")
        if psk:
            with ephemeral_psk_file(psk) as psk_path:
                self._run(cmd + ["preshared-key", psk_path], check=False)
        else:
            self._run(cmd, check=False)
        return self._peer_present(interface, pubkey)

    def _reset_peer_endpoint(self, wg: str, interface: str, pubkey: str, row: dict) -> bool:
        """Remove a peer and re-add it without a learned UDP endpoint."""
        self._run([wg, "set", interface, "peer", pubkey, "remove"], check=False)
        return self._add_peer(wg, interface, pubkey, row)

    def _peer_present(self, interface: str, pubkey: str) -> bool:
        wg = "awg" if self._interface_is_userspace_awg(interface) or shutil.which("awg") else "wg"
        result = self._run([wg, "show", interface, "peers"], check=False)
        if getattr(result, "returncode", 1) != 0:
            return False
        return pubkey in (getattr(result, "stdout", "") or "")

    def prepare_peer_for_connect(self, interface: str, pubkey: str) -> bool:
        """Drop a learned endpoint before the client dials in again."""
        return bool(self.reconcile_awg_endpoints(interface, only_pubkey=pubkey))

    def reconcile_awg_endpoints(
        self,
        interface: str,
        *,
        only_pubkey: Optional[str] = None,
        stale_sec: int = 180,
    ) -> int:
        """Clear pinned UDP endpoints that block mobile clients from reconnecting.

        Root cause (verified on live nodes): ``awg syncconf`` and disconnect keep a
        learned ``endpoint`` even when ``latest-handshake`` is ``0``. The server
        then sends to a dead UDP port and the client cannot reconnect.

        Serialized against ``apply``/``flush_stale_peers``/``teardown`` (see
        ``self._lock``) so this never removes/re-adds a peer while a full
        ``syncconf`` resync is in flight on the same interface.
        """
        import time

        with self._lock:
            wg = "awg" if self._interface_is_userspace_awg(interface) or shutil.which("awg") else "wg"
            now = int(time.time())
            handshakes = self._peer_handshakes(interface)
            endpoints = self._peer_endpoints(interface)
            dump = self._peer_dump_rows(interface)
            transfers = self.get_transfer(interface)
            bad_hosts = self._local_endpoint_hosts()
            mono = time.monotonic()
            cleared = 0
            for pubkey, endpoint in endpoints.items():
                if only_pubkey and pubkey != only_pubkey:
                    continue
                if endpoint in ("(none)", ""):
                    continue
                row = dump.get(pubkey)
                if row is None:
                    continue
                host = endpoint.rsplit(":", 1)[0]
                if host.startswith("["):
                    host = host[1:]
                hs = handshakes.get(pubkey, 0)
                rx = int(transfers.get(pubkey, {}).get("rx", 0))
                tx = int(transfers.get(pubkey, {}).get("tx", 0))
                snap = self._peer_traffic_snapshots.get(pubkey)
                traffic_busy = False
                if snap is not None:
                    last_rx, last_tx, last_mono = snap
                    traffic_busy = rx > last_rx or tx > last_tx or (mono - last_mono) < 15
                self._peer_traffic_snapshots[pubkey] = (rx, tx, mono)
                if host in bad_hosts:
                    reason = "local/bad host"
                elif hs == 0 and (rx + tx) > 0 and not traffic_busy:
                    reason = "handshake=0 (dead session)"
                elif (now - hs) > stale_sec and not traffic_busy:
                    reason = f"handshake>{stale_sec}s"
                else:
                    continue
                logger.info(
                    "Clearing AWG endpoint %s for %s… (%s)",
                    endpoint,
                    pubkey[:8],
                    reason,
                )
                if self._reset_peer_endpoint(wg, interface, pubkey, row):
                    cleared += 1
                else:
                    logger.error("Failed to re-add AWG peer %s… on %s", pubkey[:8], interface)
            return cleared

    def _ensure_spec_peers(self, wg: str, interface: str, spec: WireGuardSpec) -> None:
        """Make sure every declarative peer exists after ``syncconf``."""
        for peer in spec.peers:
            if self._peer_present(interface, peer.public_key):
                continue
            row = {
                "allowed_ips": ", ".join(peer.allowed_ips) if peer.allowed_ips else "",
                "preshared_key": peer.preshared_key,
            }
            if not self._add_peer(wg, interface, peer.public_key, row):
                logger.error(
                    "Missing AWG peer %s… on %s after apply",
                    peer.public_key[:8],
                    interface,
                )

    def flush_stale_peers(
        self,
        interface: str,
        *,
        max_age_sec: int = 35,
        idle_sec: int = 5,
        traffic_only: bool = False,
    ) -> int:
        """Clear learned endpoints for idle peers without dropping peer config.

        When ``traffic_only`` is set, only bytes transferred on the peer matter
        (safe with a short client ``PersistentKeepalive``). Mobile clients pick
        a new UDP source port on reconnect; AWG keeps stale endpoints until the
        peer is remove/re-added.

        Serialized against ``apply``/``reconcile_awg_endpoints``/``teardown``
        (see ``self._lock``) — see :meth:`reconcile_awg_endpoints` docstring.
        """
        import time

        with self._lock:
            wg = "awg" if self._interface_is_userspace_awg(interface) or shutil.which("awg") else "wg"
            now = int(time.time())
            mono = time.monotonic()
            handshakes = self._peer_handshakes(interface)
            endpoints = self._peer_endpoints(interface)
            dump = self._peer_dump_rows(interface)
            transfers = self.get_transfer(interface)
            flushed = 0
            for pubkey, endpoint in endpoints.items():
                if endpoint in ("(none)", ""):
                    continue
                row = dump.get(pubkey)
                if row is None:
                    continue
                hs = handshakes.get(pubkey, 0)
                hs_stale = not hs or (now - hs) > max_age_sec
                rx = int(transfers.get(pubkey, {}).get("rx", 0))
                tx = int(transfers.get(pubkey, {}).get("tx", 0))
                snap = self._peer_traffic_snapshots.get(pubkey)
                traffic_idle = False
                if snap is not None:
                    last_rx, last_tx, last_mono = snap
                    traffic_idle = rx == last_rx and tx == last_tx and (mono - last_mono) >= idle_sec
                self._peer_traffic_snapshots[pubkey] = (rx, tx, mono)
                if traffic_only:
                    if not traffic_idle:
                        continue
                elif not hs_stale and not traffic_idle:
                    continue
                self._reset_peer_endpoint(wg, interface, pubkey, row)
                if not self._peer_present(interface, pubkey):
                    logger.warning(
                        "AWG peer %s… missing after flush on %s; skipping",
                        pubkey[:8],
                        interface,
                    )
                    continue
                flushed += 1
            if flushed:
                logger.info("Flushed %d stale peer endpoint(s) on %s", flushed, interface)
            return flushed

    def apply(self, spec: WireGuardSpec) -> None:
        """Bring the interface to the desired state (idempotent).

        Serialized against ``reconcile_awg_endpoints``/``flush_stale_peers``/
        ``teardown`` (see ``self._lock``) so a full ``syncconf`` resync never
        interleaves with a concurrent endpoint remove/re-add on the same
        interface — that race caused transient peer drops and duplicated
        ``amneziawg-go`` teardown/recreate churn on live nodes.
        """
        with self._lock:
            use_awg = self._use_amnezia(spec)
            if spec.amnezia and not use_awg:
                logger.warning(
                    "AmneziaWG params configured but amneziawg-go is unavailable; "
                    "applying plain WireGuard on %s",
                    spec.interface,
                )
            self.ensure_interface(spec)
            conf = render_syncconf(spec, include_amnezia=use_awg)
            wg = self._wg_bin(spec)
            if use_awg and self.interface_exists(spec.interface) and self._interface_is_userspace_awg(spec.interface):
                port_res = self._run([wg, "show", spec.interface, "listen-port"], check=False)
                try:
                    current_port = int((getattr(port_res, "stdout", "") or "").strip())
                except ValueError:
                    current_port = None
                if current_port is not None and current_port != spec.listen_port:
                    logger.info(
                        "AWG %s listen port %s -> %s; recreating interface",
                        spec.interface,
                        current_port,
                        spec.listen_port,
                    )
                    self.teardown(spec.interface)
                    self.ensure_interface(spec)
            self._run([wg, "syncconf", spec.interface, "/dev/stdin"], input=conf)
            if use_awg:
                self._ensure_spec_peers(wg, spec.interface, spec)
            mode = "AmneziaWG" if use_awg else "WireGuard"
            logger.info("Applied %s spec to %s (%d peers)", mode, spec.interface, len(spec.peers))

    def get_transfer(self, interface: str) -> Dict[str, dict]:
        wg = "awg" if self._interface_is_userspace_awg(interface) or shutil.which("awg") else "wg"
        result = self._run([wg, "show", interface, "transfer"], check=False)
        if getattr(result, "returncode", 1) != 0:
            return {}
        return parse_transfer(getattr(result, "stdout", "") or "")

    def recover_awg_interface(self, interface: str) -> bool:
        """Restart userspace AWG when the daemon died but a stale TUN remains.

        Does not re-apply peer config — callers must run ``apply()`` after recovery.
        Serialized against ``apply``/``reconcile_awg_endpoints``/``flush_stale_peers``
        (see ``self._lock``).

        Returns:
            ``True`` when recovery was performed and the interface responds again;
            ``False`` when already healthy, recovery failed, or AWG is unavailable.
        """
        with self._lock:
            if not shutil.which("amneziawg-go"):
                return False
            wg = "awg" if shutil.which("awg") else "wg"
            if self._awg_daemon_running(interface):
                result = self._run([wg, "show", interface, "listen-port"], check=False)
                if getattr(result, "returncode", 1) == 0:
                    return False
            logger.warning("Recovering dead AWG interface %s", interface)
            self.teardown(interface)
            self._run(["amneziawg-go", interface], check=False)
            import time
            for _ in range(30):
                if self._awg_daemon_running(interface):
                    result = self._run([wg, "show", interface, "listen-port"], check=False)
                    if getattr(result, "returncode", 1) == 0:
                        return True
                time.sleep(0.1)
            return False

    def teardown(self, interface: str) -> None:
        """Tear down the interface (and any userspace AWG daemon) for ``interface``.

        Serialized against ``apply``/``reconcile_awg_endpoints``/
        ``flush_stale_peers`` (see ``self._lock``); reentrant-safe since
        ``apply()`` calls this internally while already holding the lock.
        """
        with self._lock:
            needle = f"amneziawg-go {interface}"
            self._run(["pkill", "-9", "-f", needle], check=False)
            import time
            for _ in range(20):
                if not self._awg_daemon_running(interface):
                    break
                time.sleep(0.1)
            if self.interface_exists(interface):
                self._run(["ip", "link", "del", "dev", interface], check=False)
                logger.info("Tore down WireGuard interface %s", interface)

    def _local_endpoint_hosts(self) -> set:
        hosts = {"127.0.0.1", "::1", "localhost"}
        result = self._run(["hostname", "-I"], check=False)
        for ip in (getattr(result, "stdout", "") or "").split():
            ip = ip.strip()
            if ip:
                hosts.add(ip)
        return hosts

    def flush_bad_endpoints(self, interface: str) -> int:
        """Backward-compatible wrapper for :meth:`reconcile_awg_endpoints`."""
        return self.reconcile_awg_endpoints(interface)
