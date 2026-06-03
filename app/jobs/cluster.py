from app import logger, scheduler
from config import CLUSTER_FAILOVER_CHECK_INTERVAL


def failover_check() -> None:
    from app.cluster import detect_failures

    try:
        detect_failures()
    except Exception:
        logger.exception("Cluster failover check failed")


if CLUSTER_FAILOVER_CHECK_INTERVAL > 0:
    logger.info(
        "Cluster failover detector enabled (every %ds)", CLUSTER_FAILOVER_CHECK_INTERVAL
    )
    from app.ha import run_if_leader

    scheduler.add_job(
        run_if_leader(failover_check),
        "interval",
        seconds=CLUSTER_FAILOVER_CHECK_INTERVAL,
        coalesce=True,
        max_instances=1,
    )
