from app import feature_flags as ff


def test_default_value():
    ff.invalidate_cache()
    assert ff.is_enabled("plugins") is False


def test_global_override():
    ff.set_flag("plugins", True)
    assert ff.is_enabled("plugins") is True
    ff.set_flag("plugins", False)
    assert ff.is_enabled("plugins") is False


def test_per_admin_override():
    ff.set_flag("rule_engine", True)              # global on
    ff.set_flag("rule_engine", False, admin_id=42)  # off for one admin
    assert ff.is_enabled("rule_engine") is True
    assert ff.is_enabled("rule_engine", admin_id=42) is False


def test_unknown_flag_defaults_false():
    assert ff.is_enabled("does_not_exist") is False
