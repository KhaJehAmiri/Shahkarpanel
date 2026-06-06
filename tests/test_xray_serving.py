"""Xray serving state must follow DB billable users."""
from unittest.mock import MagicMock, patch

import app.xray.serving as serving
from app.xray.serving import sync_core_users_now


def test_sync_core_users_hot_sync_when_core_running():
    with patch("app.xray.serving.xray") as mock_xray, patch(
        "app.xray.serving.hot_sync_main_core", return_value=True
    ) as hot_sync, patch("app.wireguard.operations.sync_user_change"):
        mock_xray.core.started = True
        sync_core_users_now()
        hot_sync.assert_called_once()
        mock_xray.core.restart.assert_not_called()


def test_sync_core_users_restarts_when_hot_sync_unavailable():
    mock_config = MagicMock()
    with patch("app.xray.serving.xray") as mock_xray, patch(
        "app.xray.serving.hot_sync_main_core", return_value=False
    ), patch("app.wireguard.operations.sync_user_change"):
        mock_xray.config.include_db_users.return_value = mock_config
        mock_xray.core.started = False
        sync_core_users_now()
        mock_xray.config.include_db_users.assert_called_once()
        mock_xray.core.restart.assert_called_once_with(mock_config)


def test_registry_rebuilds_on_new_core_generation():
    """Registry must reseed itself from the config a restarted core booted with."""
    cfg = {
        "inbounds": [
            {"tag": "Shadowsocks TCP", "settings": {"clients": [{"email": "3.hadi"}, {"email": "4.razieh"}]}},
            {"tag": "API_INBOUND", "settings": {}},
        ]
    }
    with patch("app.xray.serving.xray") as mock_xray:
        mock_xray.core.config_generation = 7
        mock_xray.core.last_config = cfg
        serving._registry_generation = -1
        serving._registered.clear()

        serving._ensure_registry_current()

        assert serving._registered["Shadowsocks TCP"] == {"3.hadi", "4.razieh"}
        assert "API_INBOUND" not in serving._registered
        assert serving._registry_generation == 7
