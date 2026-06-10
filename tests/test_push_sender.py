"""Push notification sender — unit tests (no real FCM/APNs calls)."""
from unittest.mock import MagicMock, patch

from app import feature_flags
from app.push.sender import send_to_devices


def test_send_skipped_when_flag_off():
    feature_flags.set_flag("client_push", False)
    dev = MagicMock(platform="android", token="tok")
    assert send_to_devices([dev], "t", "b") == 0


def test_send_android_uses_fcm_legacy():
    feature_flags.set_flag("client_push", True)
    dev = MagicMock(platform="android", token="tok123")
    with patch("app.push.sender._fcm_legacy", return_value=True) as m:
        assert send_to_devices([dev], "Hi", "Body") == 1
        m.assert_called_once()


def test_send_ios_uses_apns():
    feature_flags.set_flag("client_push", True)
    dev = MagicMock(platform="ios", token="apns-tok")
    with patch("app.push.sender._apns", return_value=True) as m:
        assert send_to_devices([dev], "Hi", "Body") == 1
        m.assert_called_once()
