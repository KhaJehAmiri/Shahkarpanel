"""iptables TPROXY helpers runnable inside the panel container (host netns)."""
from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Callable, Optional, Sequence

logger = logging.getLogger("shahkar-warp")

COMMENT = "shahkar-warp-tproxy"
MARK = "0x18e70"
TABLE = "51829"


def _run(cmd, check=False):
    return subprocess.run(cmd, text=True, capture_output=True, check=check)


def _flush(runner: Callable, iptables: str) -> None:
    for _ in range(64):
        listed = runner([iptables, "-t", "mangle", "-S", "PREROUTING"], check=False)
        stdout = getattr(listed, "stdout", "") or ""
        target = None
        for line in stdout.splitlines():
            if COMMENT in line and line.strip().startswith("-A "):
                target = line.strip()
                break
        if not target:
            break
        parts = target.split()
        runner([iptables, "-t", "mangle", "-D", *parts[1:]], check=False)


def _ensure_ip_rule(runner: Callable, *, enabled: bool) -> None:
    check = runner(["ip", "rule", "show", "fwmark", MARK], check=False)
    exists = MARK in (getattr(check, "stdout", "") or "") or "102000" in (
        getattr(check, "stdout", "") or ""
    )
    if enabled and not exists:
        runner(["ip", "rule", "add", "fwmark", MARK, "lookup", TABLE], check=False)
    if not enabled and exists:
        runner(["ip", "rule", "del", "fwmark", MARK, "lookup", TABLE], check=False)
    if enabled:
        runner(
            ["ip", "route", "replace", "local", "0.0.0.0/0", "dev", "lo", "table", TABLE],
            check=False,
        )
    else:
        runner(["ip", "route", "flush", "table", TABLE], check=False)


def apply_warp_tproxy(
    *,
    enabled: bool,
    subnets: Sequence[str],
    port: int,
    iptables_bin: Optional[str] = None,
) -> bool:
    iptables = iptables_bin or shutil.which("iptables") or "/usr/sbin/iptables"
    if not shutil.which("ip") and not __import__("os").path.exists("/sbin/ip"):
        logger.warning("Panel WARP TPROXY: ip binary missing")
        return False

    def runner(cmd, check=False):
        return _run(cmd, check=check)

    _flush(runner, iptables)
    if not enabled:
        _ensure_ip_rule(runner, enabled=False)
        logger.info("Panel WARP TPROXY disabled")
        return True
    if not subnets:
        _ensure_ip_rule(runner, enabled=False)
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
            if getattr(runner([iptables, "-t", "mangle", "-C", *args], check=False), "returncode", 1) != 0:
                result = runner([iptables, "-t", "mangle", "-A", *args], check=False)
                if getattr(result, "returncode", 1) != 0:
                    err = (getattr(result, "stderr", "") or "").strip()
                    logger.warning("Panel WARP TPROXY rule failed: %s", err)
                    return False
    logger.info("Panel WARP TPROXY enabled subnets=%s port=%s", list(subnets), port)
    return True
