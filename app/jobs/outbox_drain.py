"""Interval drain for user_sync_outbox (wake is the fast path)."""
from app import scheduler
from app.ha import run_if_leader


def drain_user_sync_outbox() -> None:
    from app.sync.outbox import drain

    drain()


scheduler.add_job(
    run_if_leader(drain_user_sync_outbox),
    "interval",
    seconds=10,
    coalesce=True,
    max_instances=1,
    id="user_sync_outbox_drain",
    replace_existing=True,
)
