"""Panel-side sing-box spec planner (Hysteria2 / TUIC / AnyTLS).

Pure functions that turn a node's sing-box config plus the users holding a
Hysteria2/TUIC proxy into the declarative spec consumed by the node agent's
``/singbox/apply`` endpoint, and into the ``name -> User.id`` map used for
accounting. No I/O, no DB, no transport — fully unit testable.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from app.singbox.quality import hysteria2_inbound_quality, tuic_inbound_quality
from app.singbox.speed import (
    group_users_by_tier,
    listen_port_for_user,
    speed_tier,
    tier_listen_port,
    tier_tag,
)

# Re-export for subscription helpers.
from app.singbox.speed import (  # noqa: F401
    hysteria2_port_for_user,
    hysteria2_speed_tier,
    hysteria2_tier_port,
)


def user_tag(user_id: int, username: str) -> str:
    return f"{user_id}.{username}"


@dataclass
class SBUser:
    user_id: int
    username: str
    protocol: str
    password: Optional[str] = None
    uuid: Optional[str] = None
    active: bool = True
    speed_limit_up: Optional[int] = None
    speed_limit_down: Optional[int] = None

    @property
    def name(self) -> str:
        return user_tag(self.user_id, self.username)


def _tier_rate_limits(
    tier: Optional[Tuple[int, int]],
    *,
    node_up: Optional[int] = None,
    node_down: Optional[int] = None,
) -> Tuple[Optional[int], Optional[int]]:
    if tier is None:
        return node_up, node_down
    up, down = tier
    return (up or None), (down or None)


def _build_tiered_inbounds(
    protocol: str,
    cfg: dict,
    users: List[SBUser],
    *,
    enabled_key: str,
    port_key: str,
    node_up_key: Optional[str] = None,
    node_down_key: Optional[str] = None,
    render_user,
) -> tuple[List[dict], List[dict]]:
    """Return (inbounds, traffic_limits for tc on node)."""
    if not cfg.get(enabled_key) or not cfg.get(port_key):
        return [], []
    base_port = int(cfg[port_key])
    active = [u for u in users if u.active and u.protocol == protocol]
    if not active:
        return [], []

    node_up = int(cfg[node_up_key]) if node_up_key and cfg.get(node_up_key) else None
    node_down = int(cfg[node_down_key]) if node_down_key and cfg.get(node_down_key) else None

    inbounds: List[dict] = []
    traffic_limits: List[dict] = []
    proto = "udp" if protocol in ("hysteria2", "tuic") else "tcp"

    for tier, tier_users in group_users_by_tier(active).items():
        up_mbps, down_mbps = _tier_rate_limits(
            tier, node_up=node_up, node_down=node_down
        )
        listen_port = tier_listen_port(protocol, base_port, tier)
        inbound = {
            "type": protocol,
            "tag": tier_tag(protocol, tier),
            "listen_port": listen_port,
            "certificate_path": cfg.get("certificate_path"),
            "key_path": cfg.get("key_path"),
            "users": [render_user(u) for u in tier_users],
        }
        if protocol == "hysteria2":
            inbound.update(hysteria2_inbound_quality(tier_limited=tier is not None))
            if cfg.get("hysteria2_obfs_password"):
                inbound["obfs_password"] = cfg["hysteria2_obfs_password"]
        elif protocol == "tuic":
            inbound.update(
                tuic_inbound_quality(
                    congestion_control=cfg.get("tuic_congestion_control") or "bbr"
                )
            )
        if tier is not None and (up_mbps or down_mbps):
            traffic_limits.append(
                {
                    "port": listen_port,
                    "protocol": proto,
                    "up_mbps": int(up_mbps or down_mbps or 0),
                    "down_mbps": int(down_mbps or up_mbps or 0),
                }
            )
        inbounds.append(inbound)
    return inbounds, traffic_limits


def _hysteria2_inbounds(cfg: dict, users: List[SBUser]) -> tuple[List[dict], List[dict]]:
    return _build_tiered_inbounds(
        "hysteria2",
        cfg,
        users,
        enabled_key="hysteria2_enabled",
        port_key="hysteria2_port",
        node_up_key="hysteria2_up_mbps",
        node_down_key="hysteria2_down_mbps",
        render_user=lambda u: {"name": u.name, "password": u.password or ""},
    )


def _tuic_inbounds(cfg: dict, users: List[SBUser]) -> tuple[List[dict], List[dict]]:
    return _build_tiered_inbounds(
        "tuic",
        cfg,
        users,
        enabled_key="tuic_enabled",
        port_key="tuic_port",
        render_user=lambda u: {
            "name": u.name,
            "uuid": u.uuid or "",
            "password": u.password or "",
        },
    )


def _anytls_inbounds(cfg: dict, users: List[SBUser]) -> tuple[List[dict], List[dict]]:
    return _build_tiered_inbounds(
        "anytls",
        cfg,
        users,
        enabled_key="anytls_enabled",
        port_key="anytls_port",
        render_user=lambda u: {"name": u.name, "password": u.password or ""},
    )


def build_node_spec(cfg: dict, users: List[SBUser]) -> dict:
    hy2_in, hy2_limits = _hysteria2_inbounds(cfg, users)
    inbounds = list(hy2_in)
    traffic_limits: List[dict] = list(hy2_limits)
    tuic_in, tuic_limits = _tuic_inbounds(cfg, users)
    inbounds.extend(tuic_in)
    traffic_limits.extend(tuic_limits)
    anytls_in, anytls_limits = _anytls_inbounds(cfg, users)
    inbounds.extend(anytls_in)
    traffic_limits.extend(anytls_limits)
    return {
        "inbounds": inbounds,
        "traffic_limits": traffic_limits,
        "clash_api_port": int(cfg.get("clash_api_port") or 9095),
        "clash_api_secret": cfg.get("clash_api_secret") or "",
        "v2ray_api_port": int(cfg.get("clash_api_port") or 9095) + 100,
    }


def build_name_user_map(users: List[SBUser]) -> Dict[str, int]:
    """Map every identifier sing-box/Clash might put on a counter to ``User.id``.

    The planner writes ``{id}.{username}``. Clash metadata and some v2ray-api
    builds report only the username, UUID, or the auth password (Karing / Hy2
    clients); those bytes used to be dropped (connected, not billed, never
    online).
    """
    out: Dict[str, int] = {}
    for u in users:
        out[u.name] = u.user_id
        if u.username:
            out[str(u.username)] = u.user_id
        if u.uuid:
            out[str(u.uuid)] = u.user_id
        if u.password:
            out[str(u.password)] = u.user_id
    return out


def tuic_port_for_user(base_port: int, speed_limit_up, speed_limit_down) -> int:
    return listen_port_for_user("tuic", base_port, speed_limit_up, speed_limit_down)


def anytls_port_for_user(base_port: int, speed_limit_up, speed_limit_down) -> int:
    return listen_port_for_user("anytls", base_port, speed_limit_up, speed_limit_down)
