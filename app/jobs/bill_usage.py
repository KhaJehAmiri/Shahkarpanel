from app import logger, scheduler
from app.billing.usage_billing import run_usage_billing
from app import platform_settings as ps


def _billing_interval_seconds() -> int:
    # Floor at 15s — usage recording itself is typically ~15s.
    return max(15, int(ps.get_int("billing.job_interval_seconds", 30) or 30))


def bill_usage_job():
    try:
        n = run_usage_billing()
        if n:
            logger.info("Usage billing job posted %s charge(s)", n)
        # Suspend / restore quickly after near-realtime charges.
        try:
            from app.db import GetDB
            from app.quota import enforce_reseller_traffic_caps, restore_users_everywhere

            with GetDB() as db:
                _newly, reactivated = enforce_reseller_traffic_caps(db)
            if reactivated:
                restore_users_everywhere(reactivated)
        except Exception:
            logger.exception("Usage billing cap enforcement failed")
    except Exception:
        logger.exception("Usage billing job failed")


from app.ha import run_if_leader  # noqa: E402

if ps.get_int("billing.usage_rate_per_gb", 0) > 0:
    scheduler.add_job(
        run_if_leader(bill_usage_job),
        "interval",
        seconds=_billing_interval_seconds(),
        coalesce=True,
        max_instances=1,
        id="bill_usage",
        replace_existing=True,
    )
