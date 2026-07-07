"""sing-box quality defaults for Hysteria2 / TUIC (server + client export).

Brutal CC on the server hurts real-world QUIC quality when the path cannot
sustain the declared Mbps. Prefer BBR via ``ignore_client_bandwidth`` and keep
NAT/session tuning on the listen layer instead.
"""
from __future__ import annotations

from typing import Any

# Shared listen tuning for UDP/QUIC inbounds.
QUIC_LISTEN: dict[str, Any] = {
    "udp_timeout": "10m",
    "reuse_addr": True,
}


def hysteria2_inbound_quality(*, tier_limited: bool) -> dict[str, Any]:
    """Server-side Hysteria2 profile tuned for stable QUIC."""
    return {
        **QUIC_LISTEN,
        "ignore_client_bandwidth": True,
    }


def tuic_inbound_quality(*, congestion_control: str = "bbr") -> dict[str, Any]:
    """Server-side TUIC profile tuned for stable QUIC sessions."""
    return {
        **QUIC_LISTEN,
        "congestion_control": congestion_control or "bbr",
        "heartbeat": "5s",
        "auth_timeout": "5s",
        "zero_rtt_handshake": False,
    }


def hysteria2_outbound_quality(*, tier_limited: bool) -> dict[str, Any]:
    """Client export: omit Brutal bandwidth when server uses BBR."""
    if tier_limited:
        return {}
    return {}


def tuic_outbound_quality(*, congestion_control: str = "bbr") -> dict[str, Any]:
    """Client export: native UDP relay + keepalive aligned with server."""
    return {
        "congestion_control": congestion_control or "bbr",
        "udp_relay_mode": "native",
        "heartbeat": "5s",
        "zero_rtt_handshake": False,
    }
