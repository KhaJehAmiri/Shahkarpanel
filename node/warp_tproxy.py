"""Host iptables TPROXY rules for diverting WG clients into Xray WARP."""
from __future__ import annotations

import logging
import shutil
from typing import Callable, List, Optional, Sequence

logger = logging.getLogger("nexus-wg")

COMMENT = "nxpanel-warp-tproxy"
MARK = "0x18e70"
TABLE = "51829"


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
    """Remove any mangle rules tagged with our comment."""
    for _ in range(64):
        listed = runner(["iptables", "-t", "mangle", "-S", "PREROUTING"], check=False)
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
        for proto in ("tcp", "udp"):
            args = [
                "PREROUTING",
                "-s", str(subnet),
                "-p", proto,
                "-m", "comment", "--comment", COMMENT,
                "-j", "TPROXY",
                "--on-port", str(int(port)),
                "--tproxy-mark", MARK,
            ]
            check = ["iptables", "-t", "mangle", "-C", *args]
            add = ["iptables", "-t", "mangle", "-A", *args]
            if getattr(runner(check, check=False), "returncode", 1) != 0:
                result = runner(add, check=False)
                if getattr(result, "returncode", 1) != 0:
                    err = (getattr(result, "stderr", "") or "").strip()
                    logger.warning(
                        "WARP TPROXY rule failed for %s/%s: %s",
                        subnet,
                        proto,
                        err or "unknown",
                    )
                    return False

    logger.info(
        "WARP TPROXY enabled (subnets=%s port=%s ifaces=%s)",
        list(subnets),
        port,
        list(interfaces or []),
    )
    return True
