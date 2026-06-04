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


def test_parse_marzban_single_user():
    payload = {"username": "solo", "proxies": {"vmess": {"id": "x"}}, "inbounds": {}}
    rows = parsers.parse_upload("user.json", json.dumps(payload).encode())
    assert rows[0]["username"] == "solo"


def test_parse_3xui_clients_export():
    payload = {
        "inbounds": [{"tag": "main", "protocol": "vless"}],
        "clients": [{"email": "user1@test", "enable": True, "totalGB": 5}],
    }
    rows = parsers.parse_upload("export.json", json.dumps(payload).encode())
    assert rows[0]["username"] == "user1"
    assert "vless" in rows[0]["proxies"]


def test_parse_3xui_inbounds_bundle():
    payload = {
        "inbounds": [
            {
                "tag": "in-1",
                "protocol": "vless",
                "settings": {"clients": [{"email": "client1@x", "enable": True}]},
            }
        ]
    }
    rows = parsers.parse_upload("backup.json", json.dumps(payload).encode())
    assert rows[0]["username"] == "client1"
    assert "in-1" in rows[0]["inbounds"].get("vless", [])


def test_parse_links_txt():
    text = "vless://11111111-2222-4333-8444-555555555555@1.2.3.4:443?security=tls#myuser\n"
    rows = parsers.parse_upload("links.txt", text.encode())
    assert len(rows) == 1
    assert rows[0]["username"] == "myuser"


def test_parse_pasarguard_objects():
    payload = {"objects": [{"username": "pg1", "proxies": {"trojan": {}}}]}
    result = parsers.parse_upload_with_meta("backup.json", json.dumps(payload).encode())
    assert result.source == "pasarguard"
    assert result.rows[0]["username"] == "pg1"


def test_apply_inbound_mapping():
    rows = [{"username": "a", "inbounds": {"vless": ["old-tag"]}}]
    mapped = parsers.apply_inbound_mapping(rows, {"old-tag": "new-tag"}, {"new-tag"})
    assert mapped[0]["inbounds"]["vless"] == ["new-tag"]


def test_annotate_duplicate_in_file():
    rows = [{"username": "dup"}, {"username": "dup"}]
    out = parsers.annotate_conflicts(rows, set())
    assert out[0]["conflict"] is None
    assert out[1]["conflict"] == "duplicate_in_file"


def test_count_by_conflict():
    rows = [
        {"conflict": None},
        {"conflict": "exists"},
        {"conflict": "invalid_username"},
    ]
    c = parsers.count_by_conflict(rows)
    assert c["total"] == 3
    assert c["new"] == 1
    assert c["exists"] == 1
    assert c["invalid"] == 1


def test_check_updates_uses_versions(monkeypatch):
    from app.system import update_jobs

    monkeypatch.setattr(update_jobs, "_local_version", lambda: "0.9.3")
    monkeypatch.setattr(update_jobs, "_version_at_git_ref", lambda ref: "0.9.4")
    def fake_output(*args, **kwargs):
        cmd = args[0]
        if "rev-parse" in cmd and "origin/master" in cmd:
            return "def5678"
        if "rev-parse" in cmd:
            return "abc1234"
        if "rev-list" in cmd:
            return "2"
        return "1"

    monkeypatch.setattr(update_jobs.subprocess, "check_output", fake_output)
    monkeypatch.setattr(update_jobs.subprocess, "check_call", lambda *a, **k: 0)
    monkeypatch.setattr(update_jobs, "_release_notes_for", lambda v: "- Better updates UI")
    out = update_jobs.check_updates()
    assert out["current_version"] == "0.9.3"
    assert out["remote_version"] == "0.9.4"
    assert out["commits_behind"] >= 1
    assert "Better updates" in out["release_notes"]


def test_deployment_snapshot_keys():
    from app.utils.panel_region import deployment_snapshot

    snap = deployment_snapshot()
    assert snap["panel_region"] in ("iran", "foreign")
    assert snap["detected_by"] in ("env", "geoip", "manual", "default")
