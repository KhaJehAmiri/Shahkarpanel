"""Expire unpaid portal payment intents past their TTL."""

from app import logger, scheduler
from app.db import GetDB
from app.billing.payments import expire_stale_portal_payments
from app.ha import run_if_leader


def expire_portal_payments():
    with GetDB() as db:
        n = expire_stale_portal_payments(db)
        if n:
            logger.info("Expired %s pending portal payment(s)", n)


scheduler.add_job(
    run_if_leader(expire_portal_payments),
    "interval",
    minutes=5,
    coalesce=True,
    max_instances=1,
    id="expire_portal_payments",
)
