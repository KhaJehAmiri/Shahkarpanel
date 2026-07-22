"""Default network tuning for Xray client exports and host OS.

Inbound sockopt is never injected automatically — admins configure
``streamSettings.sockopt`` explicitly in the dashboard when needed.
Host-level BBR/buffer tuning, VLESS Vision defaults, and uTLS fingerprints
for subscription links are handled here.
"""
from __future__ import annotations

import logging
import subprocess
from typing import Any

from xray_api.types.account import XTLSFlows

logger = logging.getLogger(__name__)

DEFAULT_TLS_FINGERPRINT = "chrome"

# Host kernel tuning applied on panel startup / entrypoint (--network=host).
# rmem/wmem are sized for QUIC (Hysteria2 / TUIC) — not just TCP — so unlimited
# users get large UDP buffers even when no speed-tier shaping is active.
HOST_SYSCTL_TUNING: dict[str, str] = {
    "net.ipv4.tcp_congestion_control": "bbr",
    "net.core.rmem_max": "26214400",
    "net.core.wmem_max": "26214400",
    "net.core.netdev_max_backlog": "250000",
    "net.ipv4.udp_mem": "65536 131072 262144",
}


def inbound_supports_xtls_vision(inbound: dict) -> bool:
    """True when this inbound can carry XTLS Vision (VLESS on TCP/Reality or TLS)."""
    net = inbound.get("network", "tcp")
    tls = inbound.get("tls", "none")
    header = inbound.get("header_type") or ""
    return (
        net in ("tcp", "raw", "kcp")
        and tls in ("tls", "reality")
        and header != "http"
    )


def effective_vless_flow(flow: str | None, inbound: dict) -> str:
    """Return the flow value to push into the core / subscription for VLESS.

    Vision is opt-in only: empty/missing flow stays empty (never auto-filled).
    """
    if flow and flow not in (XTLSFlows.NONE.value, "none", ""):
        return str(flow)
    return XTLSFlows.NONE.value


def default_tls_fingerprint(*, tls: str, existing: str | None = None) -> str:
    """Default uTLS fingerprint for client links when none is configured."""
    if existing:
        return str(existing)
    if str(tls or "").lower() in ("tls", "reality"):
        return DEFAULT_TLS_FINGERPRINT
    return ""


def apply_host_network_tuning() -> None:
    """Best-effort BBR + TCP/UDP buffer tuning on the host kernel (needs root)."""
    sysctl_bin = "sysctl"
    for key, value in HOST_SYSCTL_TUNING.items():
        try:
            subprocess.run(
                [sysctl_bin, "-w", f"{key}={value}"],
                check=False,
                capture_output=True,
                timeout=5,
            )
        except Exception:
            logger.debug("host sysctl %s skipped", key, exc_info=True)


def host_network_tuning_shell() -> str:
    """Shell snippet for provisioning / entrypoint (idempotent, best-effort)."""
    lines = []
    for key, value in HOST_SYSCTL_TUNING.items():
        lines.append(f"sysctl -w {key}={value} >/dev/null 2>&1 || true")
        lines.append(
            f"grep -q '^{key}={value}' /etc/sysctl.conf 2>/dev/null "
            f"|| echo '{key}={value}' >> /etc/sysctl.conf"
        )
    return "; ".join(lines)
