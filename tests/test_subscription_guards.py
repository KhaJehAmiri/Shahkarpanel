"""Central subscription config gate — same rules for Xray and WireGuard."""

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.models.proxy import ProxyTypes
from app.models.user import UserResponse, UserStatus
from app.subscription.guards import ensure_subscription_config_allowed, subscription_access


def _user(**kwargs) -> UserResponse:
    base = {
        "username": "gate-test",
        "status": UserStatus.active,
        "used_traffic": 0,
        "data_limit": None,
        "proxies": {ProxyTypes.VLESS: {}},
        "inbounds": {ProxyTypes.VLESS: []},
        "created_at": datetime.now(timezone.utc),
        "links": ["vless://example"],
        "subscription_url": "https://example/sub/x",
    }
    base.update(kwargs)
    return UserResponse.model_construct(**base)


def test_allows_active_unlimited():
    ensure_subscription_config_allowed(_user())


def test_allows_on_hold():
    ensure_subscription_config_allowed(_user(status=UserStatus.on_hold))


def test_blocks_disabled():
    with pytest.raises(HTTPException) as exc:
        ensure_subscription_config_allowed(_user(status=UserStatus.disabled))
    assert exc.value.status_code == 403
    assert "not active" in exc.value.detail.lower()


def test_blocks_limited_status():
    with pytest.raises(HTTPException) as exc:
        ensure_subscription_config_allowed(_user(status=UserStatus.limited))
    assert exc.value.status_code == 403


def test_blocks_over_quota():
    with pytest.raises(HTTPException) as exc:
        ensure_subscription_config_allowed(
            _user(data_limit=1000, used_traffic=1000),
        )
    assert exc.value.status_code == 403
    assert "limit" in exc.value.detail.lower()


def test_allows_under_quota():
    ensure_subscription_config_allowed(_user(data_limit=1000, used_traffic=999))


def test_subscription_access_allows_info_for_limited():
    access = subscription_access(_user(status=UserStatus.limited, data_limit=1000, used_traffic=1000))
    assert access["config_available"] is False
    assert access["block_reason"] == "data_limit"


def test_subscription_access_data_limit_block():
    access = subscription_access(_user(status=UserStatus.active, data_limit=1000, used_traffic=1000))
    assert access["config_available"] is False
    assert access["block_reason"] == "data_limit"


def test_subscription_access_active_ok():
    access = subscription_access(_user(status=UserStatus.active, data_limit=1000, used_traffic=500))
    assert access["config_available"] is True
    assert access["block_reason"] is None


def test_subscription_access_expired_timestamp():
    import time
    access = subscription_access(_user(status=UserStatus.active, expire=int(time.time()) - 60))
    assert access["config_available"] is False
    assert access["block_reason"] == "expired"
