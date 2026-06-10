"""Node-side sing-box engine — pure, root-free unit tests (Hysteria2/TUIC)."""
from node.singbox import (
    SingBoxInbound,
    SingBoxSpec,
    SingBoxUser,
    parse_clash_connections,
    render_config,
)


def test_spec_from_dict_filters_unsupported_types():
    spec = SingBoxSpec.from_dict({
        "inbounds": [
            {"type": "hysteria2", "tag": "hy2", "listen_port": 443,
             "users": [{"name": "1.alice", "password": "pw"}]},
            {"type": "vless", "tag": "x", "listen_port": 8443},  # dropped
        ],
    })
    assert len(spec.inbounds) == 1
    assert spec.inbounds[0].type == "hysteria2"


def test_render_hysteria2_inbound():
    spec = SingBoxSpec(inbounds=[
        SingBoxInbound(
            type="hysteria2", tag="hy2", listen_port=443,
            certificate_path="/c.pem", key_path="/k.pem",
            up_mbps=100, down_mbps=200, obfs_password="salt",
            users=[SingBoxUser(name="1.alice", password="pw")],
        )
    ])
    cfg = render_config(spec)
    inb = cfg["inbounds"][0]
    assert inb["type"] == "hysteria2"
    assert inb["listen_port"] == 443
    assert inb["users"] == [{"name": "1.alice", "password": "pw"}]
    assert inb["tls"]["enabled"] is True
    assert inb["tls"]["certificate_path"] == "/c.pem"
    assert inb["tls"]["alpn"] == ["h3"]
    assert inb["up_mbps"] == 100 and inb["down_mbps"] == 200
    assert inb["obfs"] == {"type": "salamander", "password": "salt"}


def test_render_tuic_inbound():
    spec = SingBoxSpec(inbounds=[
        SingBoxInbound(
            type="tuic", tag="tuic", listen_port=8443,
            certificate_path="/c.pem", key_path="/k.pem",
            congestion_control="bbr",
            users=[SingBoxUser(name="2.bob", uuid="uuid-1", password="pw2")],
        )
    ])
    inb = render_config(spec)["inbounds"][0]
    assert inb["type"] == "tuic"
    assert inb["users"] == [{"name": "2.bob", "uuid": "uuid-1", "password": "pw2"}]
    assert inb["congestion_control"] == "bbr"
    assert inb["tls"]["alpn"] == ["h3"]


def test_render_includes_clash_api_for_stats():
    spec = SingBoxSpec(inbounds=[], clash_api_port=9099, clash_api_secret="s3cret")
    cfg = render_config(spec)
    api = cfg["experimental"]["clash_api"]
    assert api["external_controller"] == "127.0.0.1:9099"
    assert api["secret"] == "s3cret"


def test_parse_clash_connections_sums_per_user():
    payload = {
        "connections": [
            {"upload": 100, "download": 200, "metadata": {"user": "1.alice"}},
            {"upload": 50, "download": 25, "metadata": {"user": "1.alice"}},
            {"upload": 10, "download": 10, "metadata": {"user": "2.bob"}},
            {"upload": 5, "download": 5, "metadata": {}},  # no user → ignored
        ]
    }
    out = parse_clash_connections(payload)
    assert out["1.alice"] == {"rx": 225, "tx": 150}
    assert out["2.bob"] == {"rx": 10, "tx": 10}
    assert "5" not in out


def test_parse_clash_connections_empty():
    assert parse_clash_connections({}) == {}
    assert parse_clash_connections({"connections": []}) == {}


def test_kill_stale_singbox_terminates_orphans(monkeypatch):
    from node import singbox as sb

    killed = []
    monkeypatch.setattr(sb.os, "kill", lambda pid, sig: killed.append(pid))
    monkeypatch.setattr(
        sb.subprocess, "check_output",
        lambda *a, **k: "111\n222\n",
    )
    sb._kill_stale_singbox(keep_pid=111)
    assert killed == [222]


def test_manager_restart_cleans_stale_before_start(tmp_path, monkeypatch):
    from node.singbox import SingBoxManager

    cleaned = {"n": 0}
    monkeypatch.setattr(
        "node.singbox._kill_stale_singbox",
        lambda **kw: cleaned.__setitem__("n", cleaned["n"] + 1),
    )
    mgr = SingBoxManager(config_path=str(tmp_path / "sb.json"))
    mgr.stop = lambda: None
    mgr._proc = None
    monkeypatch.setattr(mgr, "_proc", None)
    # Avoid actually spawning sing-box.
    monkeypatch.setattr(
        "node.singbox.subprocess.Popen",
        lambda *a, **k: type("P", (), {"poll": lambda s: None})(),
    )
    mgr.restart()
    assert cleaned["n"] == 1


def test_manager_apply_stops_when_no_inbounds(tmp_path):
    from node.singbox import SingBoxManager

    stopped = {"called": False}
    mgr = SingBoxManager(config_path=str(tmp_path / "sb.json"))
    mgr.stop = lambda: stopped.__setitem__("called", True)
    mgr.apply(SingBoxSpec(inbounds=[]))
    assert stopped["called"] is True
