"""Phase 11.0 — Unified accounting contract.

These tests lock the invariants that keep a single ``User.used_traffic``
authoritative across every protocol *before* WireGuard is added.  They must
keep passing unchanged once WireGuard usage is injected, which is the whole
guarantee behind "one client, many protocols, one central quota":

  1. uid is the integer ``User.id`` (Xray derives it from the ``{id}.{username}``
     stat email; WireGuard will derive it from a ``public_key -> User.id`` map).
  2. Per-source ``usage_coefficient`` is applied exactly once when merging.
  3. Only ``active`` / ``on_hold`` users accrue traffic.
  4. Multiple protocols for the same user collapse onto one counter.
  5. A second source (e.g. a WireGuard node) merges into the same
     ``User.used_traffic`` without a separate DB write path.
"""
import uuid

from app.db import GetDB
from app.db.models import Admin, Node, User
from app.jobs.record_usages import (
    BILLABLE_STATUSES,
    aggregate_user_usage,
    record_aggregated_user_usages,
)
from app.models.user import UserStatus


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _mk_user(db, status: UserStatus, admin_id=None) -> int:
    """Create a user and return its id (read inside the session so callers are
    never exposed to detached instances after later commits)."""
    u = User(username=f"acct-{uuid.uuid4().hex[:10]}", status=status, admin_id=admin_id)
    db.add(u)
    db.commit()
    return u.id


def _used(uid: int) -> int:
    with GetDB() as db:
        return db.query(User.used_traffic).filter(User.id == uid).scalar() or 0


# --------------------------------------------------------------------------- #
# Invariant 1 — uid derivation from the Xray stat email
# --------------------------------------------------------------------------- #
def test_uid_is_user_id_even_when_username_has_dots():
    """``email = f"{user.id}.{username}"`` and the collector splits on the
    *first* dot, so a username containing dots must still yield the integer id.
    This mirrors ``record_usages.get_users_stats``'s ``split('.', 1)[0]``."""
    user_id, username = 42, "first.last.vip"
    email = f"{user_id}.{username}"
    parsed = email.split(".", 1)[0]
    assert parsed == "42"
    assert int(parsed) == user_id


# --------------------------------------------------------------------------- #
# Invariant 2 — coefficient applied once, sums across sources
# --------------------------------------------------------------------------- #
def test_aggregate_applies_coefficient_once_per_source():
    api_params = {
        None: [{"uid": "1", "value": 100}],   # main core, coeff 1
        2: [{"uid": "1", "value": 100}],       # node 2, coeff 3
    }
    coeff = {None: 1, 2: 3}
    agg = {row["uid"]: row["value"] for row in aggregate_user_usage(api_params, coeff)}
    # 100*1 + 100*3 == 400, applied exactly once each.
    assert agg["1"] == 400


def test_aggregate_missing_coefficient_defaults_to_one():
    api_params = {5: [{"uid": "7", "value": 50}]}
    agg = {row["uid"]: row["value"] for row in aggregate_user_usage(api_params, {})}
    assert agg["7"] == 50


# --------------------------------------------------------------------------- #
# Invariant 3 — only active / on_hold accrue traffic
# --------------------------------------------------------------------------- #
def test_only_billable_statuses_accrue():
    assert BILLABLE_STATUSES == (UserStatus.active, UserStatus.on_hold)

    with GetDB() as db:
        active = _mk_user(db, UserStatus.active)
        on_hold = _mk_user(db, UserStatus.on_hold)
        disabled = _mk_user(db, UserStatus.disabled)
        limited = _mk_user(db, UserStatus.limited)
        expired = _mk_user(db, UserStatus.expired)

    api_params = {
        None: [
            {"uid": str(active), "value": 1000},
            {"uid": str(on_hold), "value": 1000},
            {"uid": str(disabled), "value": 1000},
            {"uid": str(limited), "value": 1000},
            {"uid": str(expired), "value": 1000},
        ]
    }
    record_aggregated_user_usages(api_params, {None: 1})

    assert _used(active) == 1000
    assert _used(on_hold) == 1000
    assert _used(disabled) == 0
    assert _used(limited) == 0
    assert _used(expired) == 0


# --------------------------------------------------------------------------- #
# Invariant 4 — many protocols, one counter
# --------------------------------------------------------------------------- #
def test_multi_protocol_same_uid_collapses_to_one_counter():
    """Two stat lines for the same user (as if from two protocols / inbounds)
    must sum into the single ``used_traffic`` field."""
    with GetDB() as db:
        user = _mk_user(db, UserStatus.active)

    api_params = {
        None: [
            {"uid": str(user), "value": 300},   # e.g. vless
            {"uid": str(user), "value": 700},   # e.g. vmess
        ]
    }
    record_aggregated_user_usages(api_params, {None: 1})
    assert _used(user) == 1000


# --------------------------------------------------------------------------- #
# Invariant 5 — a second source (WireGuard-style node) merges centrally
# --------------------------------------------------------------------------- #
def test_second_source_merges_into_same_used_traffic():
    """Simulates the future WireGuard collector: a separate node reports the
    same uid and it merges into the one ``User.used_traffic`` (with that node's
    coefficient) — no separate quota, no double write path."""
    with GetDB() as db:
        user = _mk_user(db, UserStatus.active)
        wg_node = Node(name=f"wg-{uuid.uuid4().hex[:8]}", address="10.0.0.1",
                       port=62050, api_port=62051, usage_coefficient=2.0)
        db.add(wg_node)
        db.commit()
        wg_node_id = wg_node.id

    api_params = {
        None: [{"uid": str(user), "value": 500}],          # Xray core
        wg_node_id: [{"uid": str(user), "value": 500}],     # WireGuard node, coeff 2
    }
    record_aggregated_user_usages(api_params, {None: 1, wg_node_id: 2})

    # 500*1 (xray) + 500*2 (wg) == 1500 on the single central counter.
    assert _used(user) == 1500


# --------------------------------------------------------------------------- #
# Admin usage rolls up from billable users only
# --------------------------------------------------------------------------- #
def test_admin_usage_accumulates_for_billable_only():
    with GetDB() as db:
        admin = Admin(username=f"acct-admin-{uuid.uuid4().hex[:8]}",
                      hashed_password="x", is_sudo=False)
        db.add(admin)
        db.commit()
        db.refresh(admin)
        admin_id = admin.id
        baseline = admin.users_usage or 0
        billable = _mk_user(db, UserStatus.active, admin_id=admin_id)
        non_billable = _mk_user(db, UserStatus.disabled, admin_id=admin_id)

    api_params = {
        None: [
            {"uid": str(billable), "value": 800},
            {"uid": str(non_billable), "value": 800},
        ]
    }
    record_aggregated_user_usages(api_params, {None: 1})

    with GetDB() as db:
        admin_usage = db.query(Admin.users_usage).filter(Admin.id == admin_id).scalar()
    assert admin_usage == baseline + 800


def test_empty_usage_is_noop():
    # Should not raise and should not touch the DB.
    record_aggregated_user_usages({}, {})
    record_aggregated_user_usages({None: []}, {None: 1})
