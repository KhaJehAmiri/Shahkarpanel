"""Phase 11.4 — WireGuard usage collector feeding the central used_traffic."""
import uuid

from app.db import GetDB, crud
from app.db.models import Proxy, User
from app.jobs.record_usages import aggregate_user_usage, record_aggregated_user_usages
from app.models.node import CoreKind, NodeCreate
from app.models.proxy import ProxyTypes
from app.models.user import UserStatus
from app.wireguard import generate_keypair
from app.wireguard import usage as wg_usage
from app.wireguard.usage import (
    WireGuardUsageTracker,
    build_wg_usage_params,
    collect_wg_usage_params,
    merge_wg_usage,
)


# --------------------------------------------------------------------------- #
# Delta tracker (cumulative -> per-interval)
# --------------------------------------------------------------------------- #
def test_first_observation_is_baseline_only():
    t = WireGuardUsageTracker()
    assert t.deltas(1, {"PK": {"rx": 100, "tx": 50}}) == {}


def test_delta_between_reads():
    t = WireGuardUsageTracker()
    t.deltas(1, {"PK": {"rx": 100, "tx": 50}})           # baseline 150
    assert t.deltas(1, {"PK": {"rx": 130, "tx": 70}}) == {"PK": 50}   # 200-150


def test_counter_reset_uses_current_as_delta():
    t = WireGuardUsageTracker()
    t.deltas(1, {"PK": {"rx": 1000, "tx": 1000}})        # baseline 2000
    # interface recreated -> counters dropped; current value is the delta
    assert t.deltas(1, {"PK": {"rx": 10, "tx": 5}}) == {"PK": 15}


def test_tracker_is_per_node_keyed():
    t = WireGuardUsageTracker()
    t.deltas(1, {"PK": {"rx": 100, "tx": 0}})
    t.deltas(2, {"PK": {"rx": 500, "tx": 0}})
    assert t.deltas(1, {"PK": {"rx": 150, "tx": 0}}) == {"PK": 50}
    assert t.deltas(2, {"PK": {"rx": 600, "tx": 0}}) == {"PK": 100}


def test_zero_delta_dropped():
    t = WireGuardUsageTracker()
    t.deltas(1, {"PK": {"rx": 100, "tx": 0}})
    assert t.deltas(1, {"PK": {"rx": 100, "tx": 0}}) == {}


def test_forget_node_resets_baseline():
    t = WireGuardUsageTracker()
    t.deltas(1, {"PK": {"rx": 100, "tx": 0}})
    t.forget_node(1)
    assert t.deltas(1, {"PK": {"rx": 150, "tx": 0}}) == {}  # baseline again


# --------------------------------------------------------------------------- #
# Param builder (pubkey -> uid)
# --------------------------------------------------------------------------- #
def test_build_params_maps_pubkey_to_uid():
    params = build_wg_usage_params({5: {"PKA": 100, "PKB": 200}}, {"PKA": 1, "PKB": 2})
    by_uid = {p["uid"]: p["value"] for p in params[5]}
    assert by_uid == {1: 100, 2: 200}


def test_build_params_drops_unknown_pubkey():
    params = build_wg_usage_params({5: {"PKA": 100, "GHOST": 999}}, {"PKA": 1})
    assert params[5] == [{"uid": 1, "value": 100}]


def test_build_params_aggregates_same_user():
    params = build_wg_usage_params({5: {"PKA": 100, "PKB": 50}}, {"PKA": 7, "PKB": 7})
    assert params[5] == [{"uid": 7, "value": 150}]


# --------------------------------------------------------------------------- #
# merge_wg_usage
# --------------------------------------------------------------------------- #
def test_merge_extends_and_sets_coefficient():
    api_params = {None: [{"uid": 1, "value": 10}]}
    coeff = {None: 1}
    merge_wg_usage(api_params, coeff, {9: [{"uid": 1, "value": 100}]}, {9: 2.0})
    assert api_params[9] == [{"uid": 1, "value": 100}]
    assert coeff[9] == 2.0


def test_merge_skips_empty_and_keeps_existing_coefficient():
    api_params = {9: []}
    coeff = {9: 1.5}  # WG node already present from Xray pass with its coefficient
    merge_wg_usage(api_params, coeff, {9: [{"uid": 1, "value": 100}], 8: []}, {9: 2.0})
    assert api_params[9] == [{"uid": 1, "value": 100}]
    assert coeff[9] == 1.5  # not overwritten
    assert 8 not in api_params  # empty params skipped


# --------------------------------------------------------------------------- #
# End-to-end: WG bytes land on the central User.used_traffic via the SAME path
# --------------------------------------------------------------------------- #
def _mk_active_wg_user(db):
    priv, pub = generate_keypair()
    u = User(username=f"wg-{uuid.uuid4().hex[:8]}", status=UserStatus.active)
    db.add(u)
    db.commit()
    db.add(Proxy(type=ProxyTypes.WireGuard.value,
                 settings={"private_key": priv, "public_key": pub, "address": "10.10.0.2/32"},
                 user_id=u.id))
    db.commit()
    return u.id, pub


def test_wg_usage_aggregates_with_coefficient():
    agg = aggregate_user_usage({9: [{"uid": 1, "value": 1000}]}, {9: 2.0})
    assert agg == [{"uid": 1, "value": 2000}]


def test_wg_usage_lands_on_central_used_traffic():
    with GetDB() as db:
        uid, _ = _mk_active_wg_user(db)

    record_aggregated_user_usages({9: [{"uid": uid, "value": 4096}]}, {9: 1.0})

    with GetDB() as db:
        assert db.query(User).filter(User.id == uid).first().used_traffic == 4096


def test_collect_wg_usage_params_reads_and_maps(monkeypatch):
    priv, pub = generate_keypair()

    class FakeClient:
        def transfer(self, interface):
            return {pub: {"rx": 700, "tx": 300}}

    with GetDB() as db:
        uid, _ = _mk_active_wg_user(db)
        # rebind that user's pubkey so the map resolves to `pub`
        proxy = db.query(Proxy).filter(Proxy.user_id == uid).first()
        settings = dict(proxy.settings)
        settings["public_key"] = pub
        proxy.settings = settings
        db.commit()

        dbnode = crud.create_node(
            db, NodeCreate(name=f"wg-{uuid.uuid4().hex[:6]}", address="3.3.3.3",
                           core_kind=CoreKind.wireguard))
        crud.set_node_wireguard(db, dbnode, private_key=priv, public_key=pub)
        node_id = dbnode.id

    # fresh tracker so first read isn't swallowed as baseline
    monkeypatch.setattr(wg_usage, "_tracker", WireGuardUsageTracker())
    monkeypatch.setattr(wg_usage, "_node_object", lambda nid: object())
    monkeypatch.setattr(wg_usage, "client_for_node",
                        lambda node: FakeClient() if node is not None else None)

    with GetDB() as db:
        # first read = baseline (delta 0)
        params1, _ = collect_wg_usage_params(db)
        assert params1.get(node_id, []) == []

    class FakeClient2:
        def transfer(self, interface):
            return {pub: {"rx": 1700, "tx": 300}}  # +1000 rx

    monkeypatch.setattr(wg_usage, "client_for_node",
                        lambda node: FakeClient2() if node is not None else None)
    with GetDB() as db:
        params2, coeff = collect_wg_usage_params(db)
        assert params2[node_id] == [{"uid": uid, "value": 1000}]
        assert coeff[node_id] == 1.0
