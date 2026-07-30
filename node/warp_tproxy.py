"""Host iptables TPROXY rules for diverting WG clients into Xray WARP."""
from __future__ import annotations

import logging
import shutil
from typing import Callable, List, Optional, Sequence

logger = logging.getLogger("shahkar-wg")

COMMENT = "shahkar-warp-tproxy"
MARK = "0x18e70"
TABLE = "51829"
# Inner client packets must fit in WARP's 1280 MTU (WG overhead ~60).
# Clamping SYN MSS avoids PMTUD blackholes that make apps hang while
# Cloudflare IP checks (small packets) still succeed.
TCPMSS_CLAMP = 1160


def _run_default(cmd, input=None, check=True):
    import subprocess

    return subprocess.run(cmd, input=input, text=True, capture_output=True, check=check)


def _iptables_has_tproxy(runner: Callable) -> bool:
    # TPROXY target requires xt_TPROXY; probe via help / listing.
    help_out = runner(["iptables", "-j", "TPROXY", "-h"], check=False)
    text = (getattr(help_out, "stderr", "") or "") + (getattr(help_out, "stdout", "") or "")
    if "TPROXY" in text or getattr(help_out, "returncode", 1) in (0, 2):
        # returncode 2 often means bad usage but target exists
        probe = runner(
            ["iptables", "-t", "mangle", "-C", "PREROUTING", "-p", "tcp", "-j", "TPROXY",
             "--on-port", "1", "--tproxy-mark", MARK],
            check=False,
        )
        # -C failing with "No chain" vs "Bad rule" — if binary rejects unknown target, stderr says so
        err = (getattr(probe, "stderr", "") or "").lower()
        if "tproxy" in err and ("can't" in err or "unknown" in err or "no chain/target" in err):
            if "tproxy" in err and "not found" in err:
                return False
        return True
    return shutil.which("iptables") is not None


def _flush_commented_rules(runner: Callable) -> None:
    """Remove any mangle rules tagged with our comment (PREROUTING + POSTROUTING)."""
    for chain in ("PREROUTING", "POSTROUTING"):
        for _ in range(64):
            listed = runner(["iptables", "-t", "mangle", "-S", chain], check=False)
            stdout = getattr(listed, "stdout", "") or ""
            target_line = None
            for line in stdout.splitlines():
                if COMMENT in line and line.strip().startswith("-A "):
                    target_line = line.strip()
                    break
            if not target_line:
                break
            parts = target_line.split()
            runner(["iptables", "-t", "mangle", "-D", *parts[1:]], check=False)


def _ensure_ip_rule(runner: Callable, *, enabled: bool) -> None:
    check = runner(["ip", "rule", "show", "fwmark", MARK], check=False)
    exists = MARK in (getattr(check, "stdout", "") or "") or "102000" in (getattr(check, "stdout", "") or "")
    if enabled and not exists:
        runner(["ip", "rule", "add", "fwmark", MARK, "lookup", TABLE], check=False)
    if not enabled and exists:
        runner(["ip", "rule", "del", "fwmark", MARK, "lookup", TABLE], check=False)

    route = runner(["ip", "route", "show", "table", TABLE], check=False)
    has_local = "local" in (getattr(route, "stdout", "") or "")
    if enabled and not has_local:
        runner(["ip", "route", "replace", "local", "0.0.0.0/0", "dev", "lo", "table", TABLE], check=False)
    if not enabled:
        runner(["ip", "route", "flush", "table", TABLE], check=False)


def _add_mangle(runner: Callable, chain: str, args: List[str]) -> bool:
    check = ["iptables", "-t", "mangle", "-C", chain, *args]
    add = ["iptables", "-t", "mangle", "-A", chain, *args]
    if getattr(runner(check, check=False), "returncode", 1) == 0:
        return True
    result = runner(add, check=False)
    if getattr(result, "returncode", 1) != 0:
        err = (getattr(result, "stderr", "") or "").strip()
        logger.warning("WARP TPROXY mangle rule failed (%s): %s", chain, err or "unknown")
        return False
    return True


def apply_warp_tproxy(
    *,
    enabled: bool,
    subnets: Sequence[str],
    port: int,
    interfaces: Optional[Sequence[str]] = None,
    run: Optional[Callable] = None,
) -> bool:
    """Install or remove TPROXY diversion for WG client subnets.

    Returns True when rules were applied (or cleanly removed). False when
    iptables/TPROXY is unavailable.

    DNS (udp/tcp 53) is excluded so resolvers stay local/fast — sending DNS
    through WARP made apps hang even when Cloudflare IP checks succeeded.
    TCPMSS is clamped so nested WG (client MTU 1420) inside WARP (1280) does
    not black-hole large HTTPS packets.
    """
    if not shutil.which("iptables") or not shutil.which("ip"):
        logger.warning("WARP TPROXY skipped: iptables/ip not available")
        return False

    runner = run or _run_default
    _flush_commented_rules(runner)

    if not enabled:
        _ensure_ip_rule(runner, enabled=False)
        logger.info("WARP TPROXY disabled")
        return True

    if not subnets:
        _ensure_ip_rule(runner, enabled=False)
        logger.info("WARP TPROXY enabled but no client subnets; nothing to divert")
        return True

    _ensure_ip_rule(runner, enabled=True)

    for subnet in subnets:
        # Keep DNS off the WARP path (must come BEFORE the TPROXY catch-alls).
        for proto in ("udp", "tcp"):
            if not _add_mangle(
                runner,
                "PREROUTING",
                [
                    "-s", str(subnet),
                    "-p", proto, "--dport", "53",
                    "-m", "comment", "--comment", COMMENT,
                    "-j", "RETURN",
                ],
            ):
                return False

        for proto in ("tcp", "udp"):
            if not _add_mangle(
                runner,
                "PREROUTING",
                [
                    "-s", str(subnet),
                    "-p", proto,
                    "-m", "comment", "--comment", COMMENT,
                    "-j", "TPROXY",
                    "--on-port", str(int(port)),
                    "--tproxy-mark", MARK,
                ],
            ):
                return False

        # Clamp MSS for TCP from WG clients so large segments fit WARP MTU.
        if not _add_mangle(
            runner,
            "POSTROUTING",
            [
                "-s", str(subnet),
                "-p", "tcp", "--tcp-flags", "SYN,RST", "SYN",
                "-m", "comment", "--comment", COMMENT,
                "-j", "TCPMSS", "--set-mss", str(TCPMSS_CLAMP),
            ],
        ):
            # Non-fatal: TPROXY still works; MTU blackholes may persist.
            logger.warning("WARP TCPMSS clamp failed for %s (continuing)", subnet)

    logger.info(
        "WARP TPROXY enabled (subnets=%s port=%s mss=%s ifaces=%s)",
        list(subnets),
        port,
        TCPMSS_CLAMP,
        list(interfaces or []),
    )
    return True
