"""Node host hardening: default-deny firewall + fail2ban for SSH.

Called after Xray/WG config apply so only panel-managed listen ports stay open.
Does not restrict egress (clients need full outbound); content blocks live in Xray.
"""
from __future__ import annotations

import glob
import logging
import os
import shutil
import subprocess
from typing import Iterable, List, Optional, Sequence, Set

logger = logging.getLogger("shahkar-node-harden")


def _run(cmd: List[str], *, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        check=check,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _ssh_port() -> int:
    try:
        with open("/etc/ssh/sshd_config", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) >= 2 and parts[0].lower() == "port":
                    return int(parts[1])
    except Exception:
        pass
    return int(os.environ.get("SSH_PORT") or 22)


def _ufw_active() -> bool:
    if not shutil.which("ufw"):
        return False
    out = _run(["ufw", "status"], check=False)
    return "Status: active" in (out.stdout or "")


def ensure_fail2ban_ssh() -> bool:
    """Install + enable fail2ban sshd jail when apt is available."""
    if not shutil.which("systemctl"):
        return False
    if not shutil.which("fail2ban-client"):
        if not shutil.which("apt-get"):
            logger.info("fail2ban not installed and apt-get missing — skip")
            return False
        try:
            _run(["apt-get", "update", "-qq"], check=False)
            _run(
                ["apt-get", "install", "-y", "-qq", "fail2ban"],
                check=False,
            )
        except Exception as exc:
            logger.warning("fail2ban install failed: %s", exc)
            return False
    if not shutil.which("fail2ban-client"):
        return False

    jail_dir = "/etc/fail2ban/jail.d"
    try:
        os.makedirs(jail_dir, exist_ok=True)
        jail_path = os.path.join(jail_dir, "shahkar-ssh.conf")
        with open(jail_path, "w", encoding="utf-8") as f:
            f.write(
                "[sshd]\n"
                "enabled = true\n"
                "port = ssh\n"
                "filter = sshd\n"
                "logpath = /var/log/auth.log\n"
                "maxretry = 5\n"
                "bantime = 1h\n"
                "findtime = 10m\n"
            )
        _run(["systemctl", "enable", "--now", "fail2ban"], check=False)
        _run(["fail2ban-client", "reload"], check=False)
        logger.info("fail2ban sshd jail enabled")
        return True
    except Exception as exc:
        logger.warning("fail2ban configure failed: %s", exc)
        return False


_LEFTOVER_UNIT_GLOBS = (
    "backhaul-iran*.service",
    "backhaul_premium*.service",
    "backhaul-core*.service",
)
_SYSLOG_TRUNCATE_BYTES = 1_073_741_824  # 1 GiB


def _iter_leftover_units() -> List[str]:
    found: List[str] = []
    for pattern in _LEFTOVER_UNIT_GLOBS:
        found.extend(glob.glob(f"/etc/systemd/system/{pattern}"))
        found.extend(glob.glob(f"/lib/systemd/system/{pattern}"))
        found.extend(glob.glob(f"/usr/lib/systemd/system/{pattern}"))
    # Unique basenames — systemctl wants the unit name, not the path.
    names = []
    seen = set()
    for path in found:
        name = os.path.basename(path)
        if name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def cleanup_leftover_vendor_services() -> dict:
    """Stop leftover backhaul-core leftovers that fill disk on reused VPS images.

    Panel tunnels are Xray Reality, not ``/root/backhaul-core``. A previous
    product left ``backhaul-iran*.service`` running and grew ``/var/log/syslog``
    to tens of gigabytes until the node went read-only.
    """
    result = {"stopped": [], "truncated_logs": False}
    units = _iter_leftover_units()
    leftover_dir = os.path.isdir("/root/backhaul-core")
    if not units and not leftover_dir:
        return result
    if not shutil.which("systemctl"):
        return result
    for unit in units:
        stop = _run(["systemctl", "disable", "--now", unit], check=False)
        if stop.returncode == 0:
            result["stopped"].append(unit)
            logger.warning("disabled leftover vendor unit %s", unit)
        else:
            _run(["systemctl", "stop", unit], check=False)
            _run(["systemctl", "disable", unit], check=False)
            result["stopped"].append(unit)
    syslog = "/var/log/syslog"
    try:
        if result["stopped"] and os.path.isfile(syslog) and os.path.getsize(syslog) >= _SYSLOG_TRUNCATE_BYTES:
            with open(syslog, "w", encoding="utf-8"):
                pass
            result["truncated_logs"] = True
            logger.warning("truncated %s after leftover backhaul cleanup", syslog)
    except OSError as exc:
        logger.warning("syslog truncate skipped: %s", exc)
    return result


def harden_host_firewall(
    *,
    tcp_ports: Optional[Sequence[int]] = None,
    udp_ports: Optional[Sequence[int]] = None,
    enable: bool = True,
) -> dict:
    """Default-deny UFW; allow SSH + given service ports.

    Returns a small status dict for the panel.
    """
    result = {
        "ufw": False,
        "fail2ban": False,
        "ssh_port": _ssh_port(),
        "tcp_ports": [],
        "udp_ports": [],
        "leftover": {},
        "error": None,
    }
    try:
        result["leftover"] = cleanup_leftover_vendor_services()
    except Exception as exc:
        logger.warning("leftover vendor cleanup: %s", exc)
    tcp: Set[int] = {int(p) for p in (tcp_ports or []) if int(p) > 0}
    udp: Set[int] = {int(p) for p in (udp_ports or []) if int(p) > 0}
    ssh = result["ssh_port"]
    tcp.add(ssh)
    # ACME / panel reverse-proxy on some nodes
    tcp.update({80, 443})
    result["tcp_ports"] = sorted(tcp)
    result["udp_ports"] = sorted(udp)

    try:
        result["fail2ban"] = ensure_fail2ban_ssh()
    except Exception as exc:
        logger.warning("fail2ban: %s", exc)

    if not shutil.which("ufw"):
        result["error"] = "ufw not installed"
        return result

    try:
        # Allow rules before enabling so we never lock ourselves out.
        _run(["ufw", "default", "deny", "incoming"], check=False)
        _run(["ufw", "default", "allow", "outgoing"], check=False)
        _run(
            ["ufw", "allow", f"{ssh}/tcp", "comment", "SSH"],
            check=False,
        )
        for p in sorted(tcp):
            if p == ssh:
                continue
            _run(
                ["ufw", "allow", f"{p}/tcp", "comment", "Shahkar service"],
                check=False,
            )
        for p in sorted(udp):
            _run(
                ["ufw", "allow", f"{p}/udp", "comment", "Shahkar WG/Xray UDP"],
                check=False,
            )
        if enable and not _ufw_active():
            # Non-interactive enable
            env = os.environ.copy()
            env["DEBIAN_FRONTEND"] = "noninteractive"
            subprocess.run(
                ["ufw", "--force", "enable"],
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
                env=env,
            )
        result["ufw"] = _ufw_active()
    except Exception as exc:
        result["error"] = str(exc)
        logger.warning("ufw harden failed: %s", exc)

    return result


def ports_from_xray_config_json(config_obj: dict) -> tuple[List[int], List[int]]:
    """Extract listen TCP/UDP ports from an Xray config dict."""
    tcp: Set[int] = set()
    udp: Set[int] = set()
    for inbound in config_obj.get("inbounds") or []:
        if not isinstance(inbound, dict):
            continue
        port = inbound.get("port")
        if port is None:
            continue
        try:
            port_i = int(port)
        except (TypeError, ValueError):
            continue
        if port_i <= 0:
            continue
        network = ""
        stream = inbound.get("streamSettings") or {}
        if isinstance(stream, dict):
            network = str(stream.get("network") or "").lower()
        proto = str(inbound.get("protocol") or "").lower()
        if proto == "wireguard" or network in ("quic", "kcp", "mkcp"):
            udp.add(port_i)
        else:
            tcp.add(port_i)
            if network in ("hysteria", "hysteria2"):
                udp.add(port_i)
    return sorted(tcp), sorted(udp)
