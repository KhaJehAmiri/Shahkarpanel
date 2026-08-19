"""Retry persisted Finalmask dirty slots until they land on the live core.

New WireGuard users mark a shard dirty, then a panel restart / keep-live can
drop the in-memory timer. The fingerprint cache now stores those slots; this
job re-flushes them so a brand-new account is not stuck offline.
"""
from app import scheduler
from app.ha import run_if_leader


def flush_persisted_finalmask_dirty() -> None:
    from app.wireguard.finalmask_reload import (
        peek_finalmask_dirty_slots,
        schedule_finalmask_xray_reload,
    )

    dirty = peek_finalmask_dirty_slots()
    if not dirty:
        return
    schedule_finalmask_xray_reload(delay=0.2, bulk=False)


scheduler.add_job(
    run_if_leader(flush_persisted_finalmask_dirty),
    "interval",
    seconds=20,
    coalesce=True,
    max_instances=1,
    id="finalmask_dirty_flush",
    replace_existing=True,
)
