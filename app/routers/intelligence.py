from fastapi import APIRouter, Depends, HTTPException

from app import feature_flags, intelligence
from app.db import Session, get_db
from app.models.admin import Admin
from app.utils import responses
from config import (
    INTELLIGENCE_EXHAUSTION_WINDOW_HOURS,
    INTELLIGENCE_HEAVY_FACTOR,
    INTELLIGENCE_NODE_LATENCY_MS,
)

router = APIRouter(
    tags=["Intelligence"],
    prefix="/api/intelligence",
    responses={401: responses._401, 403: responses._403},
)


def _require_enabled():
    if not feature_flags.is_enabled("traffic_intelligence"):
        raise HTTPException(status_code=404, detail="Traffic intelligence is disabled")


@router.get("/heavy-users")
def heavy_users(
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    _require_enabled()
    return intelligence.scan_heavy_users(db, factor=INTELLIGENCE_HEAVY_FACTOR)


@router.get("/exhaustion-risk")
def exhaustion_risk(
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    _require_enabled()
    return intelligence.scan_exhaustion_risk(
        db, within_hours=INTELLIGENCE_EXHAUSTION_WINDOW_HOURS
    )


@router.get("/node-risk")
def node_risk(
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    _require_enabled()
    return intelligence.scan_node_risk(db, latency_threshold_ms=INTELLIGENCE_NODE_LATENCY_MS)


@router.get("/summary")
def summary(
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Run all detectors on-demand without publishing events."""
    _require_enabled()
    return intelligence.run_scan(
        db,
        publish_events=False,
        factor=INTELLIGENCE_HEAVY_FACTOR,
        within_hours=INTELLIGENCE_EXHAUSTION_WINDOW_HOURS,
        latency_threshold_ms=INTELLIGENCE_NODE_LATENCY_MS,
    )
