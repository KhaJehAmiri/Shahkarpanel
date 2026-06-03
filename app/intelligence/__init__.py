"""Traffic intelligence orchestration.

Pulls data from the usage tables, runs the pure heuristics in
:mod:`app.intelligence.detectors`, and (optionally) publishes events so the
rule/workflow engines and webhooks can react. Gated by the
``traffic_intelligence`` feature flag at the API/job layer.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

from app.db import GetDB, Session
from app.events import EventType, publish

from . import detectors

logger = logging.getLogger("uvicorn.error")


def _usage_by_user_since(db: Session, since: datetime) -> dict:
    from sqlalchemy import func

    from app.db.models import NodeUserUsage

    rows = (
        db.query(NodeUserUsage.user_id, func.sum(NodeUserUsage.used_traffic))
        .filter(NodeUserUsage.created_at >= since)
        .group_by(NodeUserUsage.user_id)
        .all()
    )
    return {uid: int(total or 0) for uid, total in rows}


def scan_heavy_users(db: Session, factor: float = 3.0, lookback_hours: int = 24) -> list:
    """Users consuming far more than the median over the lookback window."""
    since = datetime.utcnow() - timedelta(hours=lookback_hours)
    usage = _usage_by_user_since(db, since)
    flagged_ids = detectors.heavy_users(usage, factor=factor)
    if not flagged_ids:
        return []

    from app.db.models import User

    users = {u.id: u for u in db.query(User).filter(User.id.in_(flagged_ids)).all()}
    return [
        {
            "user_id": uid,
            "username": users[uid].username if uid in users else None,
            "used_traffic_window": usage.get(uid, 0),
        }
        for uid in flagged_ids
        if uid in users
    ]


def scan_exhaustion_risk(
    db: Session, lookback_hours: int = 24, within_hours: int = 48
) -> list:
    """Active users predicted to hit their data limit within ``within_hours``."""
    since = datetime.utcnow() - timedelta(hours=lookback_hours)
    usage = _usage_by_user_since(db, since)

    from app.db.models import User
    from app.models.user import UserStatus

    at_risk = []
    candidates = (
        db.query(User)
        .filter(User.data_limit.isnot(None), User.status == UserStatus.active)
        .all()
    )
    for user in candidates:
        window = usage.get(user.id, 0)
        rate = window / lookback_hours if lookback_hours else 0
        eta = detectors.hours_to_exhaustion(user.used_traffic or 0, user.data_limit, rate)
        if eta is not None and eta <= within_hours:
            at_risk.append(
                {
                    "user_id": user.id,
                    "username": user.username,
                    "hours_to_exhaustion": round(eta, 1),
                    "rate_bytes_per_hour": int(rate),
                }
            )
    at_risk.sort(key=lambda r: r["hours_to_exhaustion"])
    return at_risk


def scan_node_risk(db: Session, latency_threshold_ms: float = 500.0) -> list:
    """Nodes that look unhealthy: errored, slow, or with a stale health probe."""
    from app.db.models import Node
    from app.models.node import NodeStatus

    flagged = []
    stale_before = datetime.utcnow() - timedelta(minutes=5)
    for node in db.query(Node).all():
        status = node.status.value if hasattr(node.status, "value") else str(node.status)
        reasons = []
        if status == NodeStatus.error.value:
            reasons.append("error_status")
        if node.latency_ms is not None and node.latency_ms > latency_threshold_ms:
            reasons.append("high_latency")
        if (
            status == NodeStatus.connected.value
            and node.last_health is not None
            and node.last_health < stale_before
        ):
            reasons.append("stale_health")
        if reasons:
            flagged.append(
                {
                    "node_id": node.id,
                    "name": node.name,
                    "latency_ms": node.latency_ms,
                    "reasons": reasons,
                }
            )
    return flagged


def run_scan(
    db: Optional[Session] = None,
    *,
    publish_events: bool = True,
    factor: float = 3.0,
    within_hours: int = 48,
    latency_threshold_ms: float = 500.0,
) -> dict:
    """Run every detector and return a summary. Optionally emit events."""
    own_session = db is None
    if own_session:
        ctx = GetDB()
        db = ctx.__enter__()
    try:
        heavy = scan_heavy_users(db, factor=factor)
        exhaustion = scan_exhaustion_risk(db, within_hours=within_hours)
        node_risk = scan_node_risk(db, latency_threshold_ms=latency_threshold_ms)
    finally:
        if own_session:
            ctx.__exit__(None, None, None)

    if publish_events:
        for item in heavy:
            publish(EventType.heavy_user_detected, item)
        for item in exhaustion:
            publish(EventType.bandwidth_exhaustion_predicted, item)
        for item in node_risk:
            publish(EventType.node_at_risk, item)

    summary = {
        "heavy_users": heavy,
        "exhaustion_risk": exhaustion,
        "node_risk": node_risk,
        "scanned_at": datetime.utcnow().isoformat(),
    }
    logger.info(
        "Intelligence scan: %d heavy, %d exhaustion-risk, %d node-risk",
        len(heavy), len(exhaustion), len(node_risk),
    )
    return summary


__all__ = [
    "detectors",
    "scan_heavy_users",
    "scan_exhaustion_risk",
    "scan_node_risk",
    "run_scan",
]
