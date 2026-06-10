"""Regression tests for audit-gap fixes (inbounds, import)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.proxy import ProxyTypes
from app.models.user import UserCreate, UserStatusCreate
from app.routers.user_import import _row_to_user_create
from app.routers.user_import import ImportRow


def test_user_create_rejects_empty_inbound_tags():
    with pytest.raises(ValidationError, match="cannot be empty"):
        UserCreate(
            username="emptytags",
            proxies={ProxyTypes.VLESS: {}},
            inbounds={ProxyTypes.VLESS: []},
            status=UserStatusCreate.active,
        )


def test_user_create_auto_fills_when_inbound_key_missing(monkeypatch):
    from app import xray

    monkeypatch.setattr(
        xray.config,
        "inbounds_by_protocol",
        {
            "vless": [{"tag": "VLESS TCP", "protocol": "vless"}],
        },
    )
    monkeypatch.setattr(
        xray.config,
        "inbounds_by_tag",
        {"VLESS TCP": {"tag": "VLESS TCP", "protocol": "vless"}},
    )

    user = UserCreate(
        username="autofill",
        proxies={ProxyTypes.VLESS: {}},
        status=UserStatusCreate.active,
    )
    assert user.inbounds[ProxyTypes.VLESS] == ["VLESS TCP"]


def test_import_row_filters_ss2022_mismatch(monkeypatch):
    from app import xray

    monkeypatch.setattr(
        xray.config,
        "inbounds_by_tag",
        {
            "SS-legacy": {"tag": "SS-legacy", "protocol": "shadowsocks", "ss_method": "aes-256-gcm"},
            "SS-2022": {"tag": "SS-2022", "protocol": "shadowsocks", "ss_method": "2022-blake3-aes-256-gcm"},
        },
    )
    monkeypatch.setattr(
        xray.config,
        "inbounds_by_protocol",
        {
            "shadowsocks": [
                {"tag": "SS-legacy", "protocol": "shadowsocks", "ss_method": "aes-256-gcm"},
                {"tag": "SS-2022", "protocol": "shadowsocks", "ss_method": "2022-blake3-aes-256-gcm"},
            ],
        },
    )

    row = ImportRow(
        username="import1",
        proxies={"shadowsocks": {"method": "2022-blake3-aes-256-gcm", "password": "x"}},
        inbounds={"shadowsocks": ["SS-legacy", "SS-2022"]},
    )
    created = _row_to_user_create(row)
    assert created.inbounds[ProxyTypes.Shadowsocks] == ["SS-2022"]
