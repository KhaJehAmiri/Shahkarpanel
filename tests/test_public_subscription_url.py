"""Public subscription URL must never point clients at localhost."""

from app.models.user import UserResponse, UserStatus
from app.subscription.public_url import public_subscription_url


def _user(**kw) -> UserResponse:
    base = {
        "username": "u1",
        "status": UserStatus.active,
        "used_traffic": 0,
        "lifetime_used_traffic": 0,
        "proxies": {},
        "subscription_url": "/sub/tok123",
    }
    base.update(kw)
    return UserResponse.model_construct(**base)


def test_uses_public_ip_when_prefix_unset(monkeypatch):
    monkeypatch.setattr("app.subscription.public_url.get_public_ip", lambda: "91.220.8.251")
    url = public_subscription_url(_user())
    assert url == "http://91.220.8.251:8000/sub/tok123/"
    assert "127.0.0.1" not in url


def test_uses_configured_prefix(monkeypatch):
    monkeypatch.setattr("app.subscription.public_url.XRAY_SUBSCRIPTION_URL_PREFIX", "https://vpn.example.com")
    url = public_subscription_url(_user(subscription_url="/sub/abc"))
    assert url == "https://vpn.example.com/sub/abc/"
