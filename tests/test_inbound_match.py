"""SS legacy vs SS-2022 inbound assignment must never mix."""
from unittest.mock import patch

from app.models.proxy import ProxyTypes
from app.xray.inbound_match import inbound_matches_proxy


def _inbounds_by_tag():
    return {
        "Shadowsocks TCP": {
            "tag": "Shadowsocks TCP",
            "protocol": "shadowsocks",
            "ss_method": "chacha20-ietf-poly1305",
            "network": "tcp",
            "port": 1080,
            "tls": "none",
            "sni": [],
            "host": [],
            "path": "",
            "fp": "",
        },
        "SS-2022": {
            "tag": "SS-2022",
            "protocol": "shadowsocks",
            "ss_method": "2022-blake3-aes-256-gcm",
            "network": "tcp",
            "port": 8388,
            "tls": "none",
            "sni": [],
            "host": [],
            "path": "",
            "fp": "",
        },
    }


def test_legacy_user_only_legacy_inbounds():
    legacy = {"method": "chacha20-ietf-poly1305", "password": "x"}
    meta = _inbounds_by_tag()
    assert inbound_matches_proxy(
        ProxyTypes.Shadowsocks, "Shadowsocks TCP", legacy, inbound_meta=meta["Shadowsocks TCP"]
    )
    assert not inbound_matches_proxy(
        ProxyTypes.Shadowsocks, "SS-2022", legacy, inbound_meta=meta["SS-2022"]
    )


def test_ss2022_user_only_2022_inbound():
    ss2022 = {"method": "2022-blake3-aes-256-gcm", "password": "x"}
    meta = _inbounds_by_tag()
    assert inbound_matches_proxy(
        ProxyTypes.Shadowsocks, "SS-2022", ss2022, inbound_meta=meta["SS-2022"]
    )
    assert not inbound_matches_proxy(
        ProxyTypes.Shadowsocks, "Shadowsocks TCP", ss2022, inbound_meta=meta["Shadowsocks TCP"]
    )


def test_subscription_skips_wrong_ss_port():
    from app.subscription.share import generate_v2ray_links

    inbounds = {
        ProxyTypes.Shadowsocks: ["Shadowsocks TCP", "so", "SS-2022"],
    }
    proxies = {
        ProxyTypes.Shadowsocks: type(
            "S",
            (),
            {
                "model_dump": lambda self: {
                    "method": "chacha20-ietf-poly1305",
                    "password": "legacy-pass",
                }
            },
        )()
    }
    with patch("app.subscription.share.xray") as mock_xray:
        mock_xray.config.inbounds_by_tag = {
            **_inbounds_by_tag(),
            "so": {
                "tag": "so",
                "protocol": "shadowsocks",
                "ss_method": "chacha20-ietf-poly1305",
                "network": "ws",
                "port": 2086,
                "tls": "none",
                "sni": [],
                "host": [],
                "path": "/",
                "fp": "",
            },
        }
        mock_xray.config.inbounds_by_protocol = {"shadowsocks": list(mock_xray.config.inbounds_by_tag.values())}
        mock_xray.hosts.get.return_value = [
            {
                "remark": "Nexus ({USERNAME})",
                "address": ["{SERVER_IP}"],
                "port": None,
                "sni": [],
                "host": [],
                "tls": None,
                "alpn": "none",
                "fingerprint": "none",
                "allowinsecure": None,
                "path": None,
                "mux_enable": False,
                "fragment_setting": None,
                "noise_setting": None,
                "random_user_agent": False,
                "use_sni_as_host": False,
            }
        ]
        extra = {
            "username": "kazem",
            "status": "active",
            "used_traffic": 0,
            "data_limit": 0,
            "expire": None,
        }
        links = generate_v2ray_links(proxies, inbounds, extra, reverse=False)
        ss_links = [l for l in links if l.startswith("ss://")]
        assert len(ss_links) == 2
        assert all(":8388" not in l for l in ss_links)
