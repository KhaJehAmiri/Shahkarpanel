"""Tests for smart panel update planning."""
from app.system.update_jobs import plan_update


def test_plan_update_restart_for_python_only():
    mode, detail = plan_update(["app/routers/user.py", "CHANGELOG.md"])
    assert mode == "restart"
    assert "bind" in detail.lower()


def test_plan_update_rebuild_for_dockerfile():
    mode, _ = plan_update(["Dockerfile"])
    assert mode == "rebuild"


def test_plan_update_pip_for_requirements():
    mode, _ = plan_update(["requirements.txt"])
    assert mode == "pip"


def test_plan_update_empty_diff_is_fast_restart():
    mode, detail = plan_update([])
    assert mode == "restart"
    assert detail
