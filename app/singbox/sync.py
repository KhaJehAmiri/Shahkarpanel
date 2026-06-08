"""Panel-side sing-box spec planner (Hysteria2 / TUIC).

Pure functions that turn a node's sing-box config plus the users holding a
Hysteria2/TUIC proxy into the declarative spec consumed by the node agent's
``/singbox/apply`` endpoint, and into the ``name -> User.id`` map used for
accounting. No I/O, no DB, no transport — fully unit testable.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional

# The per-user identity sing-box tags traffic with, so counters map back to a
# user. Matches the Xray ``email`` convention: "<user_id>.<username>".
def user_tag(user_id: int, username: str) -> str:
    return f"{user_id}.{username}"


@dataclass
class SBUser:
    """A single user's sing-box identity for one protocol on a node."""

    user_id: int
    username: str
    protocol: str                      # "hysteria2" | "tuic"
    password: Optional[str] = None
    uuid: Optional[str] = None
    active: bool = True

    @property
    def name(self) -> str:
        return user_tag(self.user_id, self.username)


def _hysteria2_inbound(cfg: dict, users: List[SBUser]) -> Optional[dict]:
    if not cfg.get("hysteria2_enabled") or not cfg.get("hysteria2_port"):
        return None
    inbound = {
        "type": "hysteria2",
        "tag": "hysteria2-in",
        "listen_port": int(cfg["hysteria2_port"]),
        "certificate_path": cfg.get("certificate_path"),
        "key_path": cfg.get("key_path"),
        "users": [
            {"name": u.name, "password": u.password or ""}
            for u in users if u.active and u.protocol == "hysteria2" and u.password
        ],
    }
    if cfg.get("hysteria2_up_mbps"):
        inbound["up_mbps"] = int(cfg["hysteria2_up_mbps"])
    if cfg.get("hysteria2_down_mbps"):
        inbound["down_mbps"] = int(cfg["hysteria2_down_mbps"])
    if cfg.get("hysteria2_obfs_password"):
        inbound["obfs_password"] = cfg["hysteria2_obfs_password"]
    return inbound


def _tuic_inbound(cfg: dict, users: List[SBUser]) -> Optional[dict]:
    if not cfg.get("tuic_enabled") or not cfg.get("tuic_port"):
        return None
    return {
        "type": "tuic",
        "tag": "tuic-in",
        "listen_port": int(cfg["tuic_port"]),
        "certificate_path": cfg.get("certificate_path"),
        "key_path": cfg.get("key_path"),
        "congestion_control": cfg.get("tuic_congestion_control") or "bbr",
        "users": [
            {"name": u.name, "uuid": u.uuid or "", "password": u.password or ""}
            for u in users if u.active and u.protocol == "tuic" and u.uuid
        ],
    }


def build_node_spec(cfg: dict, users: List[SBUser]) -> dict:
    """Build the declarative spec dict for the node agent's ``/singbox/apply``.

    Only enabled inbounds with a configured port are included; only ``active``
    users with valid credentials become inbound users so disabled/limited/
    expired users stop carrying traffic on the next sync.
    """
    inbounds = []
    hy2 = _hysteria2_inbound(cfg, users)
    if hy2 is not None:
        inbounds.append(hy2)
    tuic = _tuic_inbound(cfg, users)
    if tuic is not None:
        inbounds.append(tuic)
    return {
        "inbounds": inbounds,
        "clash_api_port": int(cfg.get("clash_api_port") or 9095),
        "clash_api_secret": cfg.get("clash_api_secret") or "",
    }


def build_name_user_map(users: List[SBUser]) -> Dict[str, int]:
    """Map ``name -> User.id`` for folding traffic counters into used_traffic.

    Includes every user (even inactive) so trailing usage is still attributed
    to the right account.
    """
    return {u.name: u.user_id for u in users}
