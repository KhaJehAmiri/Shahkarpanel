"""Shadowsocks-2022 (phase 1): key generation, account guard, share links."""
import base64

import pytest

from app.models.proxy import ShadowsocksSettings, random_ss2022_key
from app.subscription.v2ray import V2rayShareLink
from xray_api.types.account import (
    SS2022_KEY_BYTES,
    ShadowsocksAccount,
    ShadowsocksMethods,
    is_ss2022,
)


def test_ss2022_key_lengths():
    assert len(base64.b64decode(random_ss2022_key(ShadowsocksMethods.BLAKE3_AES_128_GCM))) == 16
    assert len(base64.b64decode(random_ss2022_key(ShadowsocksMethods.BLAKE3_AES_256_GCM))) == 32
    assert len(base64.b64decode(random_ss2022_key(ShadowsocksMethods.BLAKE3_CHACHA20_POLY1305))) == 32


def test_settings_mints_valid_key_for_2022():
    s = ShadowsocksSettings(method="2022-blake3-aes-256-gcm", password="not-a-key")
    assert len(base64.b64decode(s.password)) == 32

    s128 = ShadowsocksSettings(method="2022-blake3-aes-128-gcm", password="x")
    assert len(base64.b64decode(s128.password)) == 16


def test_settings_keeps_legacy_password():
    s = ShadowsocksSettings(method="chacha20-ietf-poly1305", password="keepme")
    assert s.password == "keepme"


def test_settings_revoke_respects_method():
    s = ShadowsocksSettings(method="2022-blake3-aes-256-gcm", password="x")
    first = s.password
    s.revoke()
    assert s.password != first
    assert len(base64.b64decode(s.password)) == 32


def test_account_2022_cannot_be_hot_added():
    acc = ShadowsocksAccount(
        email="1.u",
        password=random_ss2022_key(ShadowsocksMethods.BLAKE3_AES_256_GCM),
        method=ShadowsocksMethods.BLAKE3_AES_256_GCM,
    )
    assert acc.is_2022 is True
    with pytest.raises(ValueError):
        _ = acc.message


def test_account_legacy_still_serializes():
    acc = ShadowsocksAccount(email="1.u", password="p", method=ShadowsocksMethods.CHACHA20_POLY1305)
    assert acc.is_2022 is False
    assert acc.message is not None


def test_is_ss2022_helper():
    assert is_ss2022("2022-blake3-aes-256-gcm") is True
    assert is_ss2022("aes-256-gcm") is False
    assert is_ss2022("garbage") is False


def test_ss2022_share_link_encodes_server_and_user_key():
    link = V2rayShareLink.shadowsocks(
        remark="n", address="1.2.3.4", port=443,
        password="SRVKEY==:USERKEY==", method="2022-blake3-aes-256-gcm",
    )
    assert link.startswith("ss://")
    userinfo = link[len("ss://"):].split("@")[0]
    decoded = base64.b64decode(userinfo).decode()
    assert decoded == "2022-blake3-aes-256-gcm:SRVKEY==:USERKEY=="


def test_key_bytes_table_complete():
    for m in (
        ShadowsocksMethods.BLAKE3_AES_128_GCM,
        ShadowsocksMethods.BLAKE3_AES_256_GCM,
        ShadowsocksMethods.BLAKE3_CHACHA20_POLY1305,
    ):
        assert m in SS2022_KEY_BYTES
