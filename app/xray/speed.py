"""Speed-tier port helpers for panel Xray inbounds (Mbps in UI/DB)."""
from app.singbox.speed import listen_port_for_user, speed_tier, tier_listen_port, tier_tag


def ss_port_for_user(base_port: int, speed_limit_up, speed_limit_down) -> int:
    """Panel SS listens on one port; speed caps use Xray policy levels only."""
    return int(base_port)


def ss_tier_tag(tier):
    return tier_tag("ss", tier)


def ss_tier_port(base_port: int, tier):
    return tier_listen_port("shadowsocks", base_port, tier)


__all__ = ["ss_port_for_user", "ss_tier_tag", "ss_tier_port", "speed_tier"]
