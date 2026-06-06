"""Stable subscription tokens must validate (no false 404)."""
from datetime import datetime
from unittest.mock import MagicMock, patch

from app.dependencies import get_validated_sub


def test_stable_token_validates():
    dbuser = MagicMock()
    dbuser.username = "alice"
    dbuser.created_at = datetime(2026, 1, 1, 12, 0, 0)
    dbuser.sub_revoked_at = None

    with patch("app.dependencies.get_subscription_payload") as payload, patch(
        "app.dependencies.crud.get_user", return_value=dbuser
    ):
        payload.return_value = {
            "username": "alice",
            "created_at": datetime(1970, 1, 1, 0, 0, 0),
        }
        result = get_validated_sub("any-token", MagicMock())
        assert result.username == "alice"
