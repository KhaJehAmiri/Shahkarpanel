"""Online-user presence tracking.

``User.online_at`` is the only source for every "online now" number in the panel
(Overview KPI, reseller lists, per-user rows). Two properties of the old
implementation kept that number stuck at zero on busy panels:

* It was written by ``record_user_usages`` — a job that also does billing writes
  and RPyC round trips. One node lock held by a WireGuard sync (or a blocking
  SSL send to a dead node) stalled the job, and with ``max_instances=1`` every
  later tick was skipped, so ``online_at`` stopped advancing fleet-wide.
* Its signal was Xray's ``statsUserOnline``. The bundled ``StatsService`` only
  exposes ``GetStats``/``QueryStats``, and ``QueryStats`` never returns
  ``user>>>…>>>online`` rows — so that source reported nobody online, always.

Presence therefore lives here, deliberately isolated:

* Its own daemon thread plus a watchdog, so a starved APScheduler pool (or any
  unrelated hung job) cannot stop it.
* Its signal is per-user traffic counters, which every core version exposes. A
  user is online when their cumulative ``uplink+downlink`` moved since the
  previous tick. That stays correct while the usage job resets those counters:
  a reset followed by traffic reads back as a smaller-but-positive value.
  (Xray's connection-based ``statsUserOnline`` is not usable here: ``QueryStats``
  never returns the online map, and ``GetStats`` reports 0 even for users that
  are demonstrably pushing traffic on the cores we run.)
* Every core is polled in parallel with hard deadlines, and node channels are
  reached without ever waiting on a node's RPyC lock.
* Each user's *observed* activity time is kept in memory and re-written every
  tick for as long as it falls inside ``ONLINE_WINDOW_MINUTES``. A failed core
  poll or a failed database write therefore cannot drop somebody from the count
  — the next tick restores the same timestamp — while the number still means
  exactly "had traffic within the window", which is what makes a window as
  short as one minute safe.
"""

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Optional, Set, Tuple

from app.models.user import UserStatus
from config import (
    ONLINE_PRESENCE_INTERVAL,
    ONLINE_PRESENCE_QUERY_TIMEOUT,
    ONLINE_WINDOW_MINUTES,
)

logger = logging.getLogger("uvicorn.error")

BILLABLE_STATUSES = (UserStatus.active, UserStatus.on_hold)

# Cumulative per-core counters from the previous tick: {core key: {email: total}}
_snapshot: Dict[str, Dict[str, int]] = {}
_snapshot_lock = threading.Lock()

# When each user was last seen transferring: {user id: observation time}
_last_active: Dict[int, datetime] = {}
_last_active_lock = threading.Lock()

_state_lock = threading.Lock()
_state: Dict[str, object] = {
    "started_at": 0.0,
    "heartbeat": 0.0,
    "ticks": 0,
    "failures": 0,
    "sources": 0,
    "active": 0,
    "tracked": 0,
    "rows": 0,
    "last_error": None,
}

_start_lock = threading.Lock()
_worker: Optional[threading.Thread] = None
_watchdog: Optional[threading.Thread] = None
_generation = 0
_stop = threading.Event()

# Usage job already QueryStats / RPyC-polls every core and calls mark_online.
# Presence QueryStats of ``user>>>`` on every node is a second full dump of
# tens of thousands of counters — that is what pins the single worker after a
# few hours. Skip the dump while the usage job is alive; fall back only if it
# has been silent.
_USAGE_COVER_SEC = 45.0
_usage_ok_until = 0.0
_last_window_rewrite = 0.0


def note_usage_tick() -> None:
    """Called at the start of ``record_user_usages`` so presence does not
    double-QueryStats the whole fleet on the same interval."""
    global _usage_ok_until
    _usage_ok_until = time.monotonic() + _USAGE_COVER_SEC

# Consecutive empty ticks before we complain. Quiet fleets legitimately have
# none, but a broken collector shows up as a permanent streak.
_EMPTY_STREAK_WARN = 20
_empty_streak = 0

# Nodes whose stats channel could not be attached: retry occasionally instead of
# paying the dial timeout on every tick.
_ATTACH_RETRY_SEC = 60.0
_attach_after: Dict[str, float] = {}


def _beat() -> None:
    """Mark the worker alive. Called throughout a tick, not just at its start,
    so a slow poll is not mistaken for a wedged thread by the watchdog."""
    with _state_lock:
        _state["heartbeat"] = time.time()


def _interval() -> float:
    """Tick cadence, kept at several ticks per online window.

    A one-minute window with a 30s cadence would drop users on a single missed
    tick, so the configured value is capped at a quarter of the window.
    """
    configured = max(5.0, float(ONLINE_PRESENCE_INTERVAL))
    return min(configured, max(5.0, _window().total_seconds() / 4.0))


def _query_timeout() -> float:
    return max(2.0, float(ONLINE_PRESENCE_QUERY_TIMEOUT))


def _window() -> timedelta:
    return timedelta(minutes=max(1, int(ONLINE_WINDOW_MINUTES)))


def _uid_from_email(email) -> Optional[int]:
    """Xray user emails are ``<user id>.<username>``."""
    try:
        return int(str(email).split(".", 1)[0])
    except (TypeError, ValueError):
        return None


def _targets() -> Dict[str, object]:
    """Cores to poll: ``{key: XRayAPI or node}``. Cheap and lock-free."""
    from app import xray

    targets: Dict[str, object] = {}
    api = getattr(xray, "api", None)
    if api is not None:
        targets["panel"] = api
    for node_id, node in list((getattr(xray, "nodes", None) or {}).items()):
        targets[f"node:{node_id}"] = node
    return targets


def _resolve_api(key: str, target, timeout: float):
    """The gRPC stats channel for one target, or ``None`` if unreachable.

    A node adopted out-of-band — e.g. a WireGuard relay whose running core was
    soft-restored after a panel restart — has no channel attached until someone
    dials one, so checking ``has_live_api`` alone would silently skip every such
    node (and with it every user who only ever transfers there). Dialling costs
    a timeout, so an unreachable node is only retried every
    ``_ATTACH_RETRY_SEC`` rather than slowing down every tick.
    """
    if hasattr(target, "query_stats"):
        return target

    probe = getattr(target, "has_live_api", None)
    try:
        if probe is not None and probe():
            _attach_after.pop(key, None)
            return target.api
    except Exception:
        return None

    ensure = getattr(target, "ensure_api", None)
    if ensure is None:
        try:
            return target.api if getattr(target, "started", False) else None
        except Exception:
            return None
    if time.monotonic() < _attach_after.get(key, 0.0):
        return None
    try:
        attached = ensure(timeout=timeout, allow_unstarted=True)
    except TypeError:  # older signature without allow_unstarted
        try:
            attached = ensure(timeout=timeout)
        except Exception:
            attached = False
    except Exception:
        attached = False
    if not attached:
        _attach_after[key] = time.monotonic() + _ATTACH_RETRY_SEC
        return None
    _attach_after.pop(key, None)
    try:
        return target.api
    except Exception:
        return None


def _user_totals(api, timeout: float) -> Dict[str, int]:
    """``{email: uplink + downlink}`` for one core. Never resets counters."""
    totals: Dict[str, int] = {}
    for stat in api.query_stats("user>>>", reset=False, timeout=timeout):
        if stat.link not in ("uplink", "downlink"):
            continue
        try:
            totals[stat.name] = totals.get(stat.name, 0) + int(stat.value or 0)
        except (TypeError, ValueError):
            continue
    return totals


def _moved_uids(key: str, totals: Dict[str, int]) -> Set[int]:
    with _snapshot_lock:
        previous = _snapshot.get(key)
        _snapshot[key] = totals

    if previous is None:
        # First tick for this core: its counters hold everything accumulated
        # since the last reset — which after a panel restart can be hours of
        # traffic from users who are long gone. Take a baseline and report
        # nobody; real deltas start one tick later.
        return set()

    uids: Set[int] = set()
    for email, current in totals.items():
        before = previous.get(email)
        if before is None:
            # New user on a core we already track: counters start at zero, so a
            # positive value is traffic from the last tick.
            moved = current > 0
        elif current > before:
            moved = True
        else:
            # Smaller means the usage job reset the counter between ticks;
            # whatever is above zero was transferred after that reset.
            moved = 0 < current < before
        if not moved:
            continue
        uid = _uid_from_email(email)
        if uid is not None:
            uids.add(uid)
    return uids


def _poll(key: str, target, timeout: float) -> Optional[Dict[str, int]]:
    api = _resolve_api(key, target, timeout)
    if api is None:
        return None
    return _user_totals(api, timeout)


def collect_active_uids() -> Tuple[Set[int], int]:
    """User ids whose traffic counters moved since the previous tick.

    Returns ``sources=-1`` when the usage job is covering this interval so
    callers skip the empty-streak warning and the fleet QueryStats dump.
    """
    if time.monotonic() < _usage_ok_until:
        return set(), -1

    targets = _targets()
    if not targets:
        return set(), 0

    timeout = _query_timeout()
    from app.utils.concurrency import map_rpc

    def _one(key, target):
        return _poll(key, target, timeout)

    results = map_rpc(_one, targets, timeout=max(0.5, timeout * 2 + 4), default=None)
    uids: Set[int] = set()
    sources = 0
    for key, totals in results.items():
        _beat()
        if totals is None:
            continue
        sources += 1
        uids |= _moved_uids(key, totals)
    return uids, sources


def _write_online_at(stamps: Dict[datetime, Set[int]]) -> int:
    """Write ``online_at`` per observation time. Never moves a stamp backwards."""
    if not stamps:
        return 0

    from sqlalchemy.exc import OperationalError

    from app.db import GetDB
    from app.db.models import User

    last_err: Optional[BaseException] = None
    # Ascending id order + retries: traffic billing also locks ``users`` rows;
    # matching lock order cuts cross-job deadlocks with record_usages.
    for attempt in range(5):
        rows = 0
        try:
            with GetDB() as db:
                for seen_at, ids in stamps.items():
                    ordered = sorted({int(i) for i in ids})
                    for start in range(0, len(ordered), 500):
                        rows += (
                            db.query(User)
                            .filter(
                                User.id.in_(ordered[start:start + 500]),
                                User.status.in_(BILLABLE_STATUSES),
                                (User.online_at.is_(None)) | (User.online_at < seen_at),
                            )
                            .update({User.online_at: seen_at}, synchronize_session=False)
                        )
                db.commit()
            return int(rows or 0)
        except OperationalError as exc:
            last_err = exc
            orig = getattr(exc, "orig", None)
            text = f"{orig or exc}".lower()
            if "deadlock" not in text and "could not serialize" not in text:
                raise
            time.sleep(0.08 * (attempt + 1))
    if last_err:
        raise last_err
    return 0


def mark_online(uids, seen_at: Optional[datetime] = None) -> int:
    """Record ``uids`` as active now (or at ``seen_at``). Returns rows written.

    Also feeds the in-memory activity map, so callers outside the tracker (the
    usage job) extend the same source of truth.
    """
    ids = {int(uid) for uid in (uids or ()) if uid is not None}
    if not ids:
        return 0
    when = seen_at or datetime.utcnow()
    with _last_active_lock:
        for uid in ids:
            if _last_active.get(uid, when) <= when:
                _last_active[uid] = when
    return _write_online_at({when: ids})


def _due_stamps(now: datetime) -> Dict[datetime, Set[int]]:
    """Everyone seen inside the window, grouped by observation time.

    Re-writing the whole window each tick is what makes a one-minute window
    safe: a core we failed to poll, or a database write that lost a race, is
    corrected on the next tick instead of silently dropping users.
    """
    cutoff = now - _window()
    grouped: Dict[datetime, Set[int]] = {}
    with _last_active_lock:
        for uid in list(_last_active):
            seen_at = _last_active[uid]
            if seen_at < cutoff:
                del _last_active[uid]
                continue
            grouped.setdefault(seen_at, set()).add(uid)
    return grouped


def presence_tick() -> int:
    """One collect-and-stamp pass. Returns the number of users marked online."""
    global _empty_streak, _last_window_rewrite

    uids, sources = collect_active_uids()
    now = datetime.utcnow()
    if uids:
        with _last_active_lock:
            for uid in uids:
                _last_active[uid] = now
    _beat()
    # Usage job already wrote online_at via mark_online. Rewriting the whole
    # window every 15s is thousands of UPDATEs on ``users`` and is what
    # bloated dead tuples until the dashboard froze.
    now_m = time.monotonic()
    if sources >= 0 and uids:
        rows = _write_online_at({now: uids})
        _last_window_rewrite = now_m
    elif now_m - _last_window_rewrite >= 60:
        rows = _write_online_at(_due_stamps(now))
        _last_window_rewrite = now_m
    else:
        rows = 0

    with _state_lock:
        _state["ticks"] = int(_state["ticks"]) + 1
        _state["sources"] = sources
        _state["active"] = len(uids)
        _state["tracked"] = len(_last_active)
        _state["rows"] = rows
        _state["last_error"] = None

    if sources < 0:
        pass
    elif uids:
        _empty_streak = 0
    else:
        _empty_streak += 1
        if _empty_streak == _EMPTY_STREAK_WARN:
            logger.warning(
                "online presence: %s consecutive empty ticks across %s core(s) — "
                "no user traffic counters are moving",
                _empty_streak,
                sources,
            )
    return rows


def _loop(generation: int) -> None:
    interval = _interval()
    while not _stop.is_set():
        with _state_lock:
            if generation != _generation:
                return  # superseded by the watchdog
            _state["heartbeat"] = time.time()
        try:
            presence_tick()
        except Exception as exc:
            with _state_lock:
                _state["failures"] = int(_state["failures"]) + 1
                _state["last_error"] = repr(exc)
            logger.exception("online presence tick failed")
        if _stop.wait(interval):
            return


def _spawn_worker() -> None:
    global _worker, _generation

    _generation += 1
    generation = _generation
    # The counter snapshot is deliberately kept: clearing it would cost the
    # replacement worker a blind baseline tick, which is worse than the small
    # accuracy loss if a superseded worker is still writing to it.
    with _state_lock:
        _state["started_at"] = time.time()
        _state["heartbeat"] = time.time()
    _worker = threading.Thread(
        target=_loop,
        args=(generation,),
        name=f"online-presence-{generation}",
        daemon=True,
    )
    _worker.start()


def _watch() -> None:
    """Restart the worker if it dies or wedges inside a hung core RPC."""
    interval = _interval()
    while not _stop.wait(interval):
        with _state_lock:
            heartbeat = float(_state["heartbeat"] or 0.0)
        # Must fire well inside the online window, or the counter decays to zero
        # before the worker is replaced.
        stale = time.time() - heartbeat > max(interval * 4, 45.0)
        alive = _worker is not None and _worker.is_alive()
        if alive and not stale:
            continue
        logger.error(
            "online presence worker %s; restarting",
            "died" if not alive else "stalled (no heartbeat)",
        )
        with _start_lock:
            _spawn_worker()


def start_presence_worker() -> None:
    """Start presence tracking. Idempotent; safe to call from any thread."""
    global _watchdog

    with _start_lock:
        _stop.clear()
        if _worker is None or not _worker.is_alive():
            _spawn_worker()
        if _watchdog is None or not _watchdog.is_alive():
            _watchdog = threading.Thread(
                target=_watch, name="online-presence-watchdog", daemon=True
            )
            _watchdog.start()
    logger.info(
        "online presence tracker started (every %ss, query timeout %ss)",
        int(_interval()),
        int(_query_timeout()),
    )


def stop_presence_worker() -> None:
    _stop.set()


def presence_health() -> Dict[str, object]:
    """Diagnostics for the online counter (used by the system health endpoint)."""
    with _state_lock:
        snapshot = dict(_state)
    heartbeat = float(snapshot.get("heartbeat") or 0.0)
    snapshot["age"] = round(time.time() - heartbeat, 1) if heartbeat else None
    snapshot["running"] = bool(_worker is not None and _worker.is_alive())
    snapshot["interval"] = int(_interval())
    return snapshot
