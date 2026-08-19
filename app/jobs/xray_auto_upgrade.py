"""Periodic job: upgrade panel + Xray nodes to the latest Xray-core release."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import app, logger, scheduler
from app.ha import run_if_leader
from app.utils.runtime_settings import xray_auto_upgrade_config


def _xray_auto_upgrade_job() -> None:
    try:
        from app.services.xray_auto_upgrade import run_xray_auto_upgrade

        run_xray_auto_upgrade()
    except Exception:
        logger.exception("xray auto-upgrade job failed")


def reschedule_xray_auto_upgrade_job() -> None:
    cfg = xray_auto_upgrade_config()
    try:
        scheduler.remove_job("xray_auto_upgrade")
    except Exception:
        pass
    if not cfg["enabled"]:
        logger.info("xray auto-upgrade disabled")
        return
    interval = max(3600, int(cfg["interval_seconds"]))
    scheduler.add_job(
        run_if_leader(_xray_auto_upgrade_job),
        "interval",
        seconds=interval,
        coalesce=True,
        max_instances=1,
        id="xray_auto_upgrade",
        replace_existing=True,
    )
    logger.info("xray auto-upgrade scheduled every %ss", interval)


@app.on_event("startup")
def schedule_xray_auto_upgrade() -> None:
    from app.runtime_role import owns_control_plane

    if not owns_control_plane():
        return
    cfg = xray_auto_upgrade_config()
    if not cfg["enabled"]:
        logger.info("xray auto-upgrade disabled (XRAY_AUTO_UPGRADE_ENABLED=false)")
        return

    reschedule_xray_auto_upgrade_job()
    scheduler.add_job(
        run_if_leader(_xray_auto_upgrade_job),
        "date",
        run_date=datetime.now(timezone.utc) + timedelta(seconds=90),
        id="xray_auto_upgrade_boot",
        replace_existing=True,
    )
    logger.info(
        "xray auto-upgrade scheduled every %ss (boot check in 90s)",
        cfg["interval_seconds"],
    )
