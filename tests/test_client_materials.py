"""Client API protocol material builder."""
from app.client import materials as mats
from app.subscription.quic import singbox_link_insecure


class _Cfg:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def test_singbox_link_insecure_respects_trusted():
    assert singbox_link_insecure(_Cfg(tls_trusted=True, sni="vpn.example.com")) is False
    assert singbox_link_insecure(_Cfg(tls_trusted=False, sni="1.2.3.4")) is True


def test_negotiate_cdn_fallback_reorders_normal():
    from app import client as engine

    r = engine.negotiate(
        profile="normal",
        net="open",
        udp=True,
        available={"vless-reality", "cdn", "wireguard"},
        cdn_fallback=True,
    )
    assert r["usable_protocols"][0] == "vless-reality"
    assert r["usable_protocols"][1] == "cdn"
