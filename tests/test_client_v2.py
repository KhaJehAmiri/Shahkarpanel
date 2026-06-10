"""SigmaGuard client API (phase A): protocol engine, node selection, app JWT."""
import secrets

from app import client as engine
from app.db import crud
from app.utils.jwt import (
    create_app_access_token,
    create_app_refresh_token,
    get_app_payload,
    get_app_refresh_payload,
    get_portal_payload,
)


# --------------------------------------------------------------------------- #
# Protocol negotiation
# --------------------------------------------------------------------------- #
def test_gamer_open_prefers_low_latency_udp():
    r = engine.negotiate(profile="gamer", net="open", udp=True)
    assert r["recommended"] == "amneziawg"
    assert r["usable_protocols"][:2] == ["amneziawg", "hysteria2"]
    assert "tuic" not in r["usable_protocols"][:3]
    assert r["blocked_protocols"] == []


def test_gamer_without_udp_falls_back_to_tcp():
    r = engine.negotiate(profile="gamer", net="open", udp=False)
    # All UDP protocols are blocked; reality is the recommended fallback.
    assert "amneziawg" in r["blocked_protocols"]
    assert "hysteria2" in r["blocked_protocols"]
    assert "wireguard" in r["blocked_protocols"]
    assert r["recommended"] == "vless-reality"
    assert all(p not in engine.UDP_PROTOCOLS for p in r["usable_protocols"])


def test_heavily_restricted_only_camouflaged():
    r = engine.negotiate(profile="normal", net="heavily_restricted", udp=True)
    assert set(r["usable_protocols"]).issubset(engine.CAMOUFLAGED)
    assert r["recommended"] == "vless-reality"
    # Shadowsocks is not camouflage-grade under heavy DPI.
    assert "shadowsocks-2022" in r["blocked_protocols"]


def test_trader_pinned_single_protocol():
    r = engine.negotiate(profile="trader", net="restricted", udp=True)
    assert r["usable_protocols"] == ["vless-reality"]
    assert r["recommended"] == "vless-reality"


def test_unknown_profile_and_net_normalized():
    r = engine.negotiate(profile="???", net="space", udp=True)
    assert r["profile"] == "normal"
    assert r["net"] == "open"


# --------------------------------------------------------------------------- #
# Node ranking / selection
# --------------------------------------------------------------------------- #
def _nodes():
    return [
        {"id": 1, "name": "de", "region": "eu", "address": "a", "latency_ms": 120.0},
        {"id": 2, "name": "nl", "region": "eu", "address": "b", "latency_ms": 40.0},
        {"id": 3, "name": "us", "region": "na", "address": "c", "latency_ms": None},
    ]


def test_rank_nodes_by_known_latency():
    ranked = engine.rank_nodes(_nodes())
    assert [n["id"] for n in ranked] == [2, 1, 3]


def test_probe_overrides_known_latency():
    probes = [{"node_id": 1, "ping_ms": 10.0, "packet_loss_pct": 0.0}]
    ranked = engine.rank_nodes(_nodes(), probe_results=probes)
    assert ranked[0]["id"] == 1


def test_packet_loss_penalizes_node():
    probes = [
        {"node_id": 2, "ping_ms": 40.0, "packet_loss_pct": 30.0},
        {"node_id": 1, "ping_ms": 120.0, "packet_loss_pct": 0.0},
    ]
    ranked = engine.rank_nodes(_nodes(), probe_results=probes)
    # 40 + 30*20 = 640 vs 120 -> node 1 wins despite higher raw ping.
    assert ranked[0]["id"] == 1


def test_select_nodes_normal_recommends_and_falls_back():
    sel = engine.select_nodes(_nodes(), profile="normal")
    assert sel["recommended_node"] == 2
    assert sel["fallback_node"] == 1


def test_select_nodes_trader_pinned_to_bound_node():
    sel = engine.select_nodes(_nodes(), profile="trader", bound_node_id=3)
    assert sel["recommended_node"] == 3
    assert sel["fallback_node"] is None


def test_select_nodes_empty():
    sel = engine.select_nodes([], profile="normal")
    assert sel == {"recommended_node": None, "fallback_node": None}


# --------------------------------------------------------------------------- #
# App JWT
# --------------------------------------------------------------------------- #
def _ensure_secret():
    from app.db import GetDB
    from app.db.crud import get_jwt_secret_key
    from app.db.models import JWT
    from app.utils.jwt import clear_secret_key_cache

    with GetDB() as db:
        if not db.query(JWT).first():
            db.add(JWT(secret_key=secrets.token_hex(32)))
            db.commit()
        get_jwt_secret_key(db)
    clear_secret_key_cache()


def test_app_access_token_roundtrip():
    _ensure_secret()
    token = create_app_access_token("bob")
    payload = get_app_payload(token)
    assert payload and payload["username"] == "bob"
    # An access token must not validate as a refresh token (or portal token).
    assert get_app_refresh_payload(token) is None
    assert get_portal_payload(token) is None


def test_app_refresh_token_roundtrip():
    _ensure_secret()
    token = create_app_refresh_token("carol")
    payload = get_app_refresh_payload(token)
    assert payload and payload["username"] == "carol"
    assert get_app_payload(token) is None


def test_client_api_flag_default_off():
    from app import feature_flags

    assert "client_api" in feature_flags.KNOWN_FLAGS
    assert feature_flags.KNOWN_FLAGS["client_api"].default is False


# --------------------------------------------------------------------------- #
# Phase B — dedicated IP pool
# --------------------------------------------------------------------------- #
def _make_trader(db):
    from passlib.context import CryptContext

    from app.db.models import Admin as DBAdmin
    from app.models.proxy import ProxyTypes
    from app.models.user import UserCreate, UserStatus

    pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
    admin = DBAdmin(
        username=f"r-{secrets.token_hex(4)}",
        hashed_password=pwd.hash("x"),
        is_sudo=False,
        role="reseller",
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    body = UserCreate(
        username=f"trader-{secrets.token_hex(4)}",
        proxies={ProxyTypes.VMess: {"id": "00000000-0000-0000-0000-000000000077"}},
        status=UserStatus.active,
        inbounds={},
        data_limit=1024 * 1024,
        expire=1000000000,
    )
    return crud.create_user(db, body, admin=admin)


def test_dedicated_ip_assign_and_release():
    from app import dedicated_ip as svc
    from app.db import GetDB

    with GetDB() as db:
        user = _make_trader(db)
        svc.add_to_pool(db, f"203.0.113.{secrets.randbelow(250) + 1}")
        before = svc.pool_stats(db)["free"]

        ip = svc.assign_to_user(db, user.id)
        assert ip is not None and ip.user_id == user.id
        # Idempotent: a second assign returns the same IP.
        assert svc.assign_to_user(db, user.id).id == ip.id
        assert svc.get_for_user(db, user.id).address == ip.address
        assert svc.pool_stats(db)["free"] == before - 1

        assert svc.release(db, user.id) is True
        assert svc.get_for_user(db, user.id) is None


def test_dedicated_ip_pool_exhaustion():
    from app import dedicated_ip as svc
    from app.db import GetDB

    with GetDB() as db:
        # Drain any free IPs so the pool is deterministically empty.
        for ip in svc.list_pool(db, only_free=True):
            db.delete(ip)
        db.commit()
        user = _make_trader(db)
        assert svc.assign_to_user(db, user.id) is None


def test_device_and_telemetry_tables_exist():
    from sqlalchemy import inspect

    from app.db.base import engine

    tables = set(inspect(engine).get_table_names())
    assert {"client_devices", "client_telemetry", "dedicated_ips"}.issubset(tables)


# --------------------------------------------------------------------------- #
# Engine honesty — availability filtering
# --------------------------------------------------------------------------- #
def test_negotiate_filters_to_available():
    r = engine.negotiate(profile="gamer", net="open", udp=True, available={"vless-reality"})
    assert r["usable_protocols"] == ["vless-reality"]
    assert r["recommended"] == "vless-reality"
    # UDP protocols are advertised by the profile but not served → blocked.
    assert "amneziawg" in r["blocked_protocols"]
    assert "hysteria2" in r["blocked_protocols"]


def test_negotiate_picks_available_non_reality():
    r = engine.negotiate(profile="gamer", net="open", udp=True, available={"wireguard", "cdn"})
    assert r["recommended"] == "wireguard"
    assert set(r["usable_protocols"]).issubset({"wireguard", "cdn"})


def test_negotiate_nothing_available():
    r = engine.negotiate(profile="normal", net="open", udp=True, available=set())
    assert r["usable_protocols"] == []
    assert r["recommended"] is None


# --------------------------------------------------------------------------- #
# AmneziaWG config generation
# --------------------------------------------------------------------------- #
def test_amneziawg_params_emitted_under_interface():
    from app.subscription.wireguard import render_wireguard_conf

    conf = render_wireguard_conf(
        private_key="priv",
        address="10.10.0.5/32",
        server_public_key="pub",
        endpoint="1.2.3.4:51820",
        amnezia={"Jc": 4, "Jmin": 40, "Jmax": 70, "S1": 50, "S2": 100, "H1": 1, "H2": 2, "H3": 3, "H4": 4},
    )
    iface, peer = conf.split("[Peer]")
    assert "Jc = 4" in iface and "H4 = 4" in iface
    # AmneziaWG keys must sit in [Interface], never in [Peer].
    assert "Jc" not in peer


def test_plain_wireguard_has_no_amnezia_keys():
    from app.subscription.wireguard import render_wireguard_conf

    conf = render_wireguard_conf(
        private_key="priv",
        address="10.10.0.5/32",
        server_public_key="pub",
        endpoint="1.2.3.4:51820",
    )
    assert "Jc" not in conf and "H1" not in conf


def test_amnezia_params_from_node_extracts_set_fields():
    from app.subscription.wireguard import amnezia_params_from_node

    class _Cfg:
        awg_enabled = True
        awg_jc, awg_jmin, awg_jmax = 4, 40, 70
        awg_s1, awg_s2 = 50, 100
        awg_h1 = awg_h2 = awg_h3 = awg_h4 = None

    assert amnezia_params_from_node(_Cfg()) == {"Jc": 4, "Jmin": 40, "Jmax": 70, "S1": 50, "S2": 100}
    class _Off:
        awg_enabled = False
        awg_jc = 4
    assert amnezia_params_from_node(_Off()) == {}


def test_client_profile_create_and_modify():
    from app.db import GetDB
    from app.models.user import UserModify

    with GetDB() as db:
        user = _make_trader(db)
        # Default is "normal" when not specified.
        assert user.client_profile == "normal"

        crud.update_user(db, user, UserModify(client_profile="gamer"))
        db.refresh(user)
        assert user.client_profile == "gamer"

        # Omitting the field on a patch leaves it unchanged.
        crud.update_user(db, user, UserModify(note="hi"))
        db.refresh(user)
        assert user.client_profile == "gamer"


def test_client_profile_rejects_invalid():
    import pytest

    from app.models.user import UserModify

    with pytest.raises(Exception):
        UserModify(client_profile="hacker")
