import json

from app import feature_flags as ff
from app.user_import import parsers


def test_flag_specs_have_label_keys_without_phase():
    ff.invalidate_cache()
    for name, spec in ff.KNOWN_FLAGS.items():
        assert spec.label_key.startswith("flags.")
        assert "(phase" not in spec.description.lower()
        assert "(phase" not in spec.label_key


def test_feature_flag_info_shape():
    from app.routers.feature_flags import _info

    info = _info("plugins")
    assert info.label_key == "flags.plugins.desc"
    assert info.name == "plugins"


def test_parse_csv_users():
    csv_text = "username,limit_gb,expire,note,protocols\nalice,10,0,note1,vless\n"
    rows = parsers.parse_upload("users.csv", csv_text.encode())
    assert len(rows) == 1
    assert rows[0]["username"] == "alice"
    assert rows[0]["data_limit"] == 10 * 1024**3


def test_parse_marzban_json():
    payload = {"users": [{"username": "bob", "proxies": {"vless": {}}, "data_limit": 0}]}
    rows = parsers.parse_upload("users.json", json.dumps(payload).encode())
    assert rows[0]["username"] == "bob"


def test_parse_3xui_clients_export():
    payload = {
        "inbounds": [{"tag": "main", "protocol": "vless"}],
        "clients": [{"email": "user1@test", "enable": True, "totalGB": 5}],
    }
    rows = parsers.parse_upload("export.json", json.dumps(payload).encode())
    assert rows[0]["username"] == "user1"
    assert "vless" in rows[0]["proxies"]


def test_apply_inbound_mapping():
    rows = [{"username": "a", "inbounds": {"vless": ["old-tag"]}}]
    mapped = parsers.apply_inbound_mapping(rows, {"old-tag": "new-tag"}, {"new-tag"})
    assert mapped[0]["inbounds"]["vless"] == ["new-tag"]


def test_deployment_snapshot_keys():
    from app.utils.panel_region import deployment_snapshot

    snap = deployment_snapshot()
    assert snap["panel_region"] in ("iran", "foreign")
    assert snap["detected_by"] in ("env", "geoip", "manual", "default")
