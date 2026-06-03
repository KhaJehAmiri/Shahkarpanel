from app import logger, scheduler
from config import (
    INTELLIGENCE_EXHAUSTION_WINDOW_HOURS,
    INTELLIGENCE_HEAVY_FACTOR,
    INTELLIGENCE_NODE_LATENCY_MS,
    INTELLIGENCE_SCAN_INTERVAL,
)


def intelligence_scan() -> None:
    from app import feature_flags
    from app.intelligence import run_scan

    if not feature_flags.is_enabled("traffic_intelligence"):
        return
    try:
        run_scan(
            publish_events=True,
            factor=INTELLIGENCE_HEAVY_FACTOR,
            within_hours=INTELLIGENCE_EXHAUSTION_WINDOW_HOURS,
            latency_threshold_ms=INTELLIGENCE_NODE_LATENCY_MS,
        )
    except Exception:
        logger.exception("Traffic intelligence scan failed")


if INTELLIGENCE_SCAN_INTERVAL > 0:
    from app.ha import run_if_leader

    logger.info("Traffic intelligence scan enabled (every %ds)", INTELLIGENCE_SCAN_INTERVAL)
    scheduler.add_job(
        run_if_leader(intelligence_scan),
        "interval",
        seconds=INTELLIGENCE_SCAN_INTERVAL,
        coalesce=True,
        max_instances=1,
    )
