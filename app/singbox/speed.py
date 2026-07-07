"""Speed-limit tier helpers shared by sing-box protocol planners (Mbps in UI/DB)."""
from typing import Dict, List, Optional, Tuple

# Per-protocol port offsets so tier listen ports never collide on one node.
PROTOCOL_SPEED_OFFSET = {
    "hysteria2": 100,
    "tuic": 1000,
    "anytls": 2000,
    "shadowsocks": 100,
}


def speed_tier(
    speed_limit_up: Optional[int],
    speed_limit_down: Optional[int],
) -> Optional[Tuple[int, int]]:
    """Stable (up, down) Mbps tier key, or None when unlimited."""
    if not speed_limit_up and not speed_limit_down:
        return None
    return (int(speed_limit_up or 0), int(speed_limit_down or 0))


def tier_listen_port(
    protocol: str,
    base_port: int,
    tier: Optional[Tuple[int, int]],
) -> int:
    if tier is None:
        return int(base_port)
    up, down = tier
    offset = PROTOCOL_SPEED_OFFSET.get(protocol, 100)
    # Use both up and down so (10,10) and (10,5) never share a listen port.
    return int(base_port) + offset + int(up) + int(down) * 100


def listen_port_for_user(
    protocol: str,
    base_port: int,
    speed_limit_up: Optional[int],
    speed_limit_down: Optional[int],
) -> int:
    return tier_listen_port(
        protocol,
        base_port,
        speed_tier(speed_limit_up, speed_limit_down),
    )


def tier_tag(protocol: str, tier: Optional[Tuple[int, int]]) -> str:
    if tier is None:
        return f"{protocol}-in"
    up, down = tier
    return f"{protocol}-in-{up}-{down}"


def group_users_by_tier(users: List) -> Dict[Optional[Tuple[int, int]], list]:
    tiers: Dict[Optional[Tuple[int, int]], list] = {}
    for user in users:
        tiers.setdefault(speed_tier(user.speed_limit_up, user.speed_limit_down), []).append(user)
    return tiers


# Backward-compatible Hysteria2 names used by subscription code.
hysteria2_speed_tier = speed_tier
hysteria2_tier_port = lambda base_port, tier: tier_listen_port("hysteria2", base_port, tier)
hysteria2_port_for_user = lambda base_port, up, down: listen_port_for_user(
    "hysteria2", base_port, up, down
)
