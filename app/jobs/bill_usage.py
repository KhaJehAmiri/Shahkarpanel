from app import logger, scheduler
from app.billing.usage_billing import run_usage_billing
from app import platform_settings as ps


def bill_usage_job():
    try:
        n = run_usage_billing()
        if n:
            logger.info("Usage billing job posted %s charge(s)", n)
    except Exception:
        logger.exception("Usage billing job failed")


from app.ha import run_if_leader  # noqa: E402

if ps.get_int("billing.usage_rate_per_gb", 0) > 0:
    scheduler.add_job(
        run_if_leader(bill_usage_job),
        "interval",
        seconds=ps.get_int("billing.job_interval_seconds", 3600),
        coalesce=True,
        max_instances=1,
    )
