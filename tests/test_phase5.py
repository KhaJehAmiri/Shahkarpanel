from datetime import datetime, timedelta

from app import intelligence, marketplace
from app.db import GetDB
from app.db.models import NodeUserUsage, User
from app.intelligence import detectors
from app.models.user import UserStatus

# ---- Pure detectors ----

def test_heavy_users_flags_outliers():
    usage = {1: 10, 2: 12, 3: 11, 4: 500}
    assert detectors.heavy_users(usage, factor=3.0) == [4]


def test_heavy_users_needs_minimum_sample():
    assert detectors.heavy_users({1: 100, 2: 1}, factor=3.0) == []


def test_hours_to_exhaustion_math():
    # 50 of 100 used, burning 10/h -> 5h left.
    assert detectors.hours_to_exhaustion(50, 100, 10) == 5.0
    assert detectors.hours_to_exhaustion(50, None, 10) is None
    assert detectors.hours_to_exhaustion(50, 100, 0) is None
    assert detectors.hours_to_exhaustion(200, 100, 10) == 0.0


def test_anomaly_detection():
    baseline = [10, 11, 9, 10, 10, 11]
    assert detectors.is_anomalous(100, baseline, threshold=3.0)
    assert not detectors.is_anomalous(11, baseline, threshold=3.0)


def test_latency_trend_sign():
    assert detectors.latency_trend([10, 20, 30]) > 0
    assert detectors.latency_trend([30, 20, 10]) < 0


# ---- Orchestration over DB ----

def test_scan_exhaustion_risk_uses_recent_usage():
    now = datetime.utcnow()
    with GetDB() as db:
        user = User(
            username="intel-user",
            status=UserStatus.active,
            used_traffic=900,
            data_limit=1000,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        # 100 bytes consumed over the last hour -> ~100 B/h -> ~1h to limit.
        db.add(
            NodeUserUsage(
                created_at=now - timedelta(minutes=30), user_id=user.id, node_id=None,
                used_traffic=100,
            )
        )
        db.commit()

        risk = intelligence.scan_exhaustion_risk(db, lookback_hours=1, within_hours=48)
        assert any(r["username"] == "intel-user" for r in risk)


def test_run_scan_returns_summary_without_publishing():
    with GetDB() as db:
        summary = intelligence.run_scan(db, publish_events=False)
    assert set(summary) >= {"heavy_users", "exhaustion_risk", "node_risk", "scanned_at"}


# ---- Marketplace ----

def test_catalog_sync_and_install():
    with GetDB() as db:
        marketplace.sync_catalog(db)
        plugins = marketplace.list_plugins(db)
        names = {p.name for p in plugins}
        assert {"event_log", "node_alert", "auto_heal"}.issubset(names)

        plugin = marketplace.install(db, "auto_heal")
        assert plugin.installed and plugin.enabled

        plugin = marketplace.uninstall(db, "auto_heal")
        assert not plugin.installed and not plugin.enabled


def test_reviews_update_average_rating():
    with GetDB() as db:
        marketplace.sync_catalog(db)
        plugin = marketplace.get_plugin(db, "event_log")

        marketplace.add_review(db, plugin, admin_id=1, rating=4)
        marketplace.add_review(db, plugin, admin_id=2, rating=2)
        assert marketplace.average_rating(plugin) == 3.0
        assert plugin.rating_count == 2

        # Same admin re-reviews -> replaces, count stays 2.
        marketplace.add_review(db, plugin, admin_id=1, rating=2)
        assert plugin.rating_count == 2
        assert marketplace.average_rating(plugin) == 2.0
