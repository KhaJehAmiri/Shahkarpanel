"""Hysteria2 / TUIC subscription link generators (pure unit tests)."""
from types import SimpleNamespace

from app.subscription.quic import (
    hysteria2_link,
    tuic_link,
    user_hysteria2_link,
    user_tuic_link,
)


def _node(**kw):
    defaults = dict(
        address="1.2.3.4",
        name="de",
        singbox=SimpleNamespace(
            hysteria2_enabled=True,
            hysteria2_port=443,
            hysteria2_obfs_password="salt",
            tuic_enabled=True,
            tuic_port=8443,
            tuic_congestion_control="bbr",
            sni="vpn.example.com",
        ),
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def test_hysteria2_link_with_obfs():
    link = hysteria2_link(
        password="pw", host="vpn.example.com", port=443,
        sni="vpn.example.com", obfs_password="salt", remark="n1",
    )
    assert link.startswith("hysteria2://pw@vpn.example.com:443?")
    assert "insecure=1" in link
    assert "obfs=salamander" in link
    assert "obfs-password=salt" in link
    assert link.endswith("#n1")


def test_tuic_link_format():
    link = tuic_link(
        uuid="u-1", password="pw2", host="vpn.example.com", port=8443,
        sni="vpn.example.com", remark="n2",
    )
    assert link.startswith("tuic://")
    assert "congestion_control=bbr" in link
    assert "insecure=1" in link
    assert "allow_insecure=1" in link
    assert "udp_relay_mode=native" in link
    assert "alpn=h3" in link
    assert "@vpn.example.com:8443" in link


def test_user_hysteria2_link_from_node():
    link = user_hysteria2_link({"password": "secret"}, _node(), remark="r")
    assert link and link.startswith("hysteria2://")
    assert "vpn.example.com:443" in link


def test_user_tuic_link_requires_uuid():
    assert user_tuic_link({"password": "x"}, _node()) is None
    link = user_tuic_link({"uuid": "u-9", "password": "x"}, _node())
    assert link and link.startswith("tuic://")
