"""Panel-host Cloudflare WARP via a kernel WireGuard interface + policy routing.

Tunnel-exit topology terminates client WG on the panel (``wg0``/``wg1``), then
historically MASQUERADE'd out ``eth0`` (server IP). When a relay has
``warp_enabled``, we instead:

1. Bring up ``nxwarp0`` with the WARP account keys (kernel WG — reserved is
   optional; Cloudflare still handshakes without it).
2. ``ip rule from <client-subnet> lookup 51828`` → ``default dev nxwarp0``.
3. MASQUERADE client subnets out ``nxwarp0`` (not ``eth0``).

This avoids TPROXY/CAP_NET_ADMIN issues with the panel's non-root Xray.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from typing import Optional, Sequence

logger = logging.getLogger("nexuspanel-warp")

WARP_IFACE = "nxwarp0"
WARP_TABLE = "51828"
WARP_RULE_PRIORITY_BASE = 100
COMMENT_MASQ = "nxpanel-warp-wg-masq"


def _run(cmd: list[str], check: bool = False, input_text: Optional[str] = None):
    return subprocess.run(
        cmd,
        input=input_text,
        text=True,
        capture_output=True,
        check=check,
    )


def _which(name: str) -> Optional[str]:
    return shutil.which(name)


def teardown_warp_iface() -> None:
    _run(["ip", "link", "del", WARP_IFACE], check=False)
    _run(["ip", "route", "flush", "table", WARP_TABLE], check=False)
    # Remove our policy rules (best-effort scan)
    listed = _run(["ip", "rule", "show"], check=False)
    for line in (listed.stdout or "").splitlines():
        if f"lookup {WARP_TABLE}" in line or f"lookup {WARP_TABLE} " in line:
            # e.g. "100:	from 10.10.0.0/20 lookup 51828"
            parts = line.split()
            try:
                # ip rule del from X lookup TABLE
                if "from" in parts:
                    idx = parts.index("from")
                    src = parts[idx + 1]
                    _run(
                        ["ip", "rule", "del", "from", src, "lookup", WARP_TABLE],
                        check=False,
                    )
            except Exception:
                continue


def _ensure_iface(private_key: str, address: str, peer_public: str, endpoint: str) -> bool:
    if not _which("wg") or not _which("ip"):
        logger.warning("wg/ip missing; cannot create WARP interface")
        return False

    # Create iface if needed
    links = _run(["ip", "-br", "link", "show", WARP_IFACE], check=False)
    if getattr(links, "returncode", 1) != 0:
        add = _run(["ip", "link", "add", WARP_IFACE, "type", "wireguard"], check=False)
        if getattr(add, "returncode", 1) != 0:
            logger.warning("Failed to create %s: %s", WARP_IFACE, add.stderr)
            return False

    with tempfile.NamedTemporaryFile("w", delete=False) as fh:
        fh.write(private_key.strip() + "\n")
        key_path = fh.name
    try:
        os.chmod(key_path, 0o600)
        result = _run(
            [
                "wg", "set", WARP_IFACE,
                "private-key", key_path,
                "peer", peer_public,
                "endpoint", endpoint,
                "allowed-ips", "0.0.0.0/0,::/0",
                "persistent-keepalive", "25",
            ],
            check=False,
        )
        if getattr(result, "returncode", 1) != 0:
            logger.warning("wg set failed: %s", result.stderr)
            return False
    finally:
        try:
            os.unlink(key_path)
        except OSError:
            pass

    _run(["ip", "address", "flush", "dev", WARP_IFACE], check=False)
    _run(["ip", "address", "add", address, "dev", WARP_IFACE], check=False)
    _run(["ip", "link", "set", "mtu", "1280", "dev", WARP_IFACE], check=False)
    _run(["ip", "link", "set", "up", "dev", WARP_IFACE], check=False)

    # Kernel WG auto-adds AllowedIPs into the main table — remove so only
    # policy-routing table 51828 uses nxwarp0 as default.
    _run(["ip", "route", "del", "default", "dev", WARP_IFACE], check=False)
    _run(["ip", "route", "del", "0.0.0.0/0", "dev", WARP_IFACE], check=False)
    _run(["ip", "route", "del", "::/0", "dev", WARP_IFACE], check=False)

    # Pin Cloudflare endpoint on the main uplink (never via nxwarp0).
    host = endpoint.rsplit(":", 1)[0]
    route = _run(["ip", "route", "get", host], check=False)
    parts = (route.stdout or "").split()
    try:
        via = parts[parts.index("via") + 1] if "via" in parts else None
        dev = parts[parts.index("dev") + 1] if "dev" in parts else None
        if via and dev and dev != WARP_IFACE:
            _run(
                ["ip", "route", "replace", f"{host}/32", "via", via, "dev", dev],
                check=False,
            )
        elif dev and dev != WARP_IFACE:
            _run(
                ["ip", "route", "replace", f"{host}/32", "dev", dev],
                check=False,
            )
    except (ValueError, IndexError):
        pass

    return True


def _flush_nat_comment(iptables: str) -> None:
    for _ in range(32):
        listed = _run([iptables, "-t", "nat", "-S", "POSTROUTING"], check=False)
        line = None
        for raw in (listed.stdout or "").splitlines():
            if COMMENT_MASQ in raw and raw.strip().startswith("-A "):
                line = raw.strip()
                break
        if not line:
            break
        parts = line.split()
        _run([iptables, "-t", "nat", "-D", *parts[1:]], check=False)


def _set_policy_routes(subnets: Sequence[str]) -> None:
    # Clear previous table + rules for our table
    listed = _run(["ip", "rule", "show"], check=False)
    for line in (listed.stdout or "").splitlines():
        if f"lookup {WARP_TABLE}" in line and "from" in line:
            parts = line.split()
            try:
                src = parts[parts.index("from") + 1]
                _run(["ip", "rule", "del", "from", src, "lookup", WARP_TABLE], check=False)
            except (ValueError, IndexError):
                continue
    _run(["ip", "route", "flush", "table", WARP_TABLE], check=False)

    for i, subnet in enumerate(subnets):
        prio = WARP_RULE_PRIORITY_BASE + i
        _run(
            ["ip", "rule", "add", "from", str(subnet), "lookup", WARP_TABLE, "priority", str(prio)],
            check=False,
        )
    _run(["ip", "route", "replace", "default", "dev", WARP_IFACE, "table", WARP_TABLE], check=False)


def _set_nat(subnets: Sequence[str], *, enabled: bool) -> None:
    iptables = _which("iptables") or "/usr/sbin/iptables"
    _flush_nat_comment(iptables)
    if not enabled:
        return
    for subnet in subnets:
        args = [
            "POSTROUTING",
            "-s", str(subnet),
            "-o", WARP_IFACE,
            "-m", "comment", "--comment", COMMENT_MASQ,
            "-j", "MASQUERADE",
        ]
        if getattr(_run([iptables, "-t", "nat", "-C", *args], check=False), "returncode", 1) != 0:
            _run([iptables, "-t", "nat", "-I", *args], check=False)


def _suppress_eth0_masq(subnets: Sequence[str], *, suppress: bool) -> None:
    """When WARP is on, remove eth0 MASQUERADE for client subnets so traffic cannot leak."""
    iptables = _which("iptables") or "/usr/sbin/iptables"
    # Broader /24 variants from older provisioning too
    candidates: list[str] = []
    for s in subnets:
        candidates.append(str(s))
        if str(s).endswith("/20"):
            candidates.append(str(s).rsplit("/", 1)[0] + "/24")
    for subnet in dict.fromkeys(candidates):
        for out_dev in ("eth0", "ens3", "enp0s3", "enp1s0"):
            args = ["POSTROUTING", "-s", subnet, "-o", out_dev, "-j", "MASQUERADE"]
            exists = getattr(_run([iptables, "-t", "nat", "-C", *args], check=False), "returncode", 1) == 0
            if suppress and exists:
                _run([iptables, "-t", "nat", "-D", *args], check=False)
            # When re-enabling DIRECT we do not recreate eth0 MASQ here —
            # ensure_egress_forwarding / host sync will restore it.


def apply_panel_warp_wg(
    *,
    enabled: bool,
    subnets: Sequence[str],
    private_key: str = "",
    address: str = "",
    peer_public: str = "",
    endpoint: str = "",
) -> bool:
    """Enable or disable panel WARP WG egress for the given client subnets."""
    if not enabled:
        _set_nat([], enabled=False)
        teardown_warp_iface()
        logger.info("Panel WARP WG egress disabled")
        return True

    if not subnets or not private_key or not address or not peer_public or not endpoint:
        logger.warning("Panel WARP WG egress missing credentials or subnets")
        return False

    if not _ensure_iface(private_key, address, peer_public, endpoint):
        return False

    _set_policy_routes(subnets)
    _set_nat(subnets, enabled=True)
    _suppress_eth0_masq(subnets, suppress=True)
    logger.info(
        "Panel WARP WG egress enabled iface=%s subnets=%s endpoint=%s",
        WARP_IFACE,
        list(subnets),
        endpoint,
    )
    return True
