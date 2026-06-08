"""Panel-side sing-box integration — pure unit tests (Hysteria2 / TUIC)."""
from app.singbox.sync import SBUser, build_name_user_map, build_node_spec, user_tag
from app.singbox.transport import RESTSingBoxClient, RPyCSingBoxClient, client_for_node
from app.singbox.usage import SingBoxUsageTracker, build_singbox_usage_params

CFG = {
    "certificate_path": "/c.pem", "key_path": "/k.pem", "sni": "vpn.example.com",
    "clash_api_port": 9099, "clash_api_secret": "sek",
    "hysteria2_enabled": True, "hysteria2_port": 443,
    "hysteria2_up_mbps": 100, "hysteria2_down_mbps": 200, "hysteria2_obfs_password": "salt",
    "tuic_enabled": True, "tuic_port": 8443, "tuic_congestion_control": "bbr",
}


def _users():
    return [
        SBUser(user_id=1, username="alice", protocol="hysteria2", password="hp", active=True),
        SBUser(user_id=2, username="bob", protocol="tuic", uuid="u-2", password="tp", active=True),
        SBUser(user_id=3, username="carol", protocol="hysteria2", password="hp3", active=False),
    ]


def test_user_tag_format():
    assert user_tag(7, "dave") == "7.dave"
    assert SBUser(user_id=7, username="dave", protocol="tuic").name == "7.dave"


def test_build_node_spec_includes_both_inbounds():
    spec = build_node_spec(CFG, _users())
    types = {i["type"] for i in spec["inbounds"]}
    assert types == {"hysteria2", "tuic"}
    assert spec["clash_api_port"] == 9099
    assert spec["clash_api_secret"] == "sek"


def test_hysteria2_inbound_active_users_only():
    spec = build_node_spec(CFG, _users())
    hy2 = next(i for i in spec["inbounds"] if i["type"] == "hysteria2")
    names = [u["name"] for u in hy2["users"]]
    assert names == ["1.alice"]  # carol is inactive → excluded
    assert hy2["up_mbps"] == 100 and hy2["down_mbps"] == 200
    assert hy2["obfs_password"] == "salt"
    assert hy2["certificate_path"] == "/c.pem"


def test_tuic_inbound_carries_uuid():
    spec = build_node_spec(CFG, _users())
    tuic = next(i for i in spec["inbounds"] if i["type"] == "tuic")
    assert tuic["users"] == [{"name": "2.bob", "uuid": "u-2", "password": "tp"}]
    assert tuic["congestion_control"] == "bbr"


def test_disabled_protocol_omitted():
    cfg = dict(CFG, tuic_enabled=False)
    spec = build_node_spec(cfg, _users())
    assert {i["type"] for i in spec["inbounds"]} == {"hysteria2"}


def test_missing_port_omits_inbound():
    cfg = dict(CFG, hysteria2_port=None)
    spec = build_node_spec(cfg, _users())
    assert {i["type"] for i in spec["inbounds"]} == {"tuic"}


def test_build_name_user_map_includes_inactive():
    m = build_name_user_map(_users())
    assert m == {"1.alice": 1, "2.bob": 2, "3.carol": 3}


def test_usage_tracker_deltas_and_reset():
    t = SingBoxUsageTracker()
    assert t.deltas(1, {"1.alice": {"rx": 100, "tx": 100}}) == {}  # baseline
    assert t.deltas(1, {"1.alice": {"rx": 150, "tx": 150}}) == {"1.alice": 100}
    # counter reset (sing-box restarted) → current value is the delta
    assert t.deltas(1, {"1.alice": {"rx": 10, "tx": 5}}) == {"1.alice": 15}


def test_build_usage_params_drops_unknown_names():
    deltas = {5: {"1.alice": 100, "9.ghost": 50}}
    params = build_singbox_usage_params(deltas, {"1.alice": 1})
    assert params[5] == [{"uid": 1, "value": 100}]


# --- transport fakes -------------------------------------------------------

class _FakeRest:
    def __init__(self):
        self.calls = []

    def make_request(self, path, timeout, **kw):
        self.calls.append((path, kw))
        if path == "/singbox/transfer":
            return {"transfer": {"1.alice": {"rx": 1, "tx": 2}}}
        return {}


class _FakeRemote:
    def __init__(self):
        self.applied = None
        self.downed = False

    def singbox_apply_json(self, payload):
        self.applied = payload

    def singbox_transfer(self):
        return '{"2.bob": {"rx": 3, "tx": 4}}'

    def singbox_down(self):
        self.downed = True


class _FakeRpycNode:
    def __init__(self):
        self.remote = _FakeRemote()


def test_client_for_node_detects_rest_and_rpyc():
    rest = type("N", (), {"make_request": lambda *a, **k: None})()
    assert isinstance(client_for_node(rest), RESTSingBoxClient)
    assert isinstance(client_for_node(_FakeRpycNode()), RPyCSingBoxClient)
    assert client_for_node(None) is None


def test_rest_client_apply_and_transfer():
    node = _FakeRest()
    client = RESTSingBoxClient(node)
    client.apply({"inbounds": []})
    assert client.transfer() == {"1.alice": {"rx": 1, "tx": 2}}
    assert node.calls[0][0] == "/singbox/apply"


def test_rpyc_client_apply_transfer_down():
    node = _FakeRpycNode()
    client = RPyCSingBoxClient(node)
    client.apply({"inbounds": [{"type": "tuic"}]})
    assert "tuic" in node.remote.applied
    assert client.transfer() == {"2.bob": {"rx": 3, "tx": 4}}
    client.down()
    assert node.remote.downed is True
