"""Phase 11.1 — WireGuard data model (keys, pool, settings, enum)."""
import base64
import uuid

from app.db import GetDB
from app.db.models import Proxy, User
from app.models.proxy import ProxySettings, ProxyTypes, WireGuardSettings
from app.models.user import UserStatus
from app.wireguard import (
    WireGuardPeerIPAllocator,
    generate_keypair,
    generate_preshared_key,
    public_key_from_private,
)


# --------------------------------------------------------------------------- #
# Keys
# --------------------------------------------------------------------------- #
def test_generate_keypair_is_valid_base64_32_bytes():
    priv, pub = generate_keypair()
    assert priv != pub
    assert len(base64.b64decode(priv)) == 32
    assert len(base64.b64decode(pub)) == 32


def test_public_key_is_deterministic_from_private():
    priv, pub = generate_keypair()
    assert public_key_from_private(priv) == pub


def test_preshared_key_is_32_bytes():
    psk = generate_preshared_key()
    assert len(base64.b64decode(psk)) == 32
    assert generate_preshared_key() != generate_preshared_key()


# --------------------------------------------------------------------------- #
# Peer IP pool
# --------------------------------------------------------------------------- #
def test_allocator_reserves_first_host_and_yields_unique():
    alloc = WireGuardPeerIPAllocator("10.10.0.0/24")
    a = alloc.allocate()
    b = alloc.allocate()
    # .1 is reserved for the interface, so peers start at .2
    assert a == "10.10.0.2/32"
    assert b == "10.10.0.3/32"
    assert a != b


def test_allocator_skips_used():
    alloc = WireGuardPeerIPAllocator("10.10.0.0/24", used=["10.10.0.2/32"])
    assert alloc.allocate() == "10.10.0.3/32"


def test_allocator_exhaustion_returns_none():
    # /30 has hosts .1 and .2; .1 reserved -> only .2 allocatable.
    alloc = WireGuardPeerIPAllocator("10.10.0.0/30")
    assert alloc.allocate() == "10.10.0.2/32"
    assert alloc.allocate() is None


# --------------------------------------------------------------------------- #
# Settings model
# --------------------------------------------------------------------------- #
def test_wireguard_settings_autogenerates_matching_keys():
    s = WireGuardSettings()
    assert s.private_key
    assert s.public_key == public_key_from_private(s.private_key)
    assert s.address is None


def test_wireguard_settings_fills_public_from_given_private():
    priv, pub = generate_keypair()
    s = WireGuardSettings(private_key=priv)
    assert s.public_key == pub


def test_wireguard_settings_keeps_panel_kind_marker():
    s = WireGuardSettings.model_validate({"nexusPanelKind": "amneziawg"})
    dumped = s.dict(no_obj=True)
    assert dumped["nexusPanelKind"] == "amneziawg"


def test_wireguard_settings_revoke_rotates_keys():
    s = WireGuardSettings()
    old_priv, old_pub = s.private_key, s.public_key
    s.revoke()
    assert s.private_key != old_priv
    assert s.public_key != old_pub
    assert s.public_key == public_key_from_private(s.private_key)


def test_proxytypes_has_wireguard_and_factory():
    assert ProxyTypes("wireguard") is ProxyTypes.WireGuard
    assert ProxyTypes.WireGuard.settings_model is WireGuardSettings
    # WireGuard is not provisioned as an Xray account.
    assert ProxyTypes.WireGuard.account_model is None
    assert ProxyTypes.WireGuard.is_xray_account is False
    assert ProxyTypes.VLESS.is_xray_account is True


def test_proxysettings_from_dict_roundtrip_for_wireguard():
    priv, pub = generate_keypair()
    s = ProxySettings.from_dict(ProxyTypes.WireGuard, {"private_key": priv})
    assert isinstance(s, WireGuardSettings)
    assert s.public_key == pub
    dumped = s.dict(no_obj=True)
    assert dumped["private_key"] == priv
    assert dumped["public_key"] == pub


# --------------------------------------------------------------------------- #
# Persistence: a WireGuard proxy stores/loads on the same Proxy table
# --------------------------------------------------------------------------- #
def test_wireguard_proxy_persists_on_user():
    priv, pub = generate_keypair()
    with GetDB() as db:
        u = User(username=f"wg-{uuid.uuid4().hex[:8]}", status=UserStatus.active)
        db.add(u)
        db.commit()
        db.add(Proxy(type=ProxyTypes.WireGuard.value,
                     settings={"private_key": priv, "public_key": pub,
                               "address": "10.10.0.2/32"},
                     user_id=u.id))
        db.commit()
        uid = u.id

    with GetDB() as db:
        proxy = db.query(Proxy).filter(Proxy.user_id == uid).first()
        assert proxy.type is ProxyTypes.WireGuard
        assert proxy.settings["public_key"] == pub
