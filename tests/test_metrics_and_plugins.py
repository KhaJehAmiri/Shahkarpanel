from app import feature_flags as ff
from app import plugins
from app.metrics import render_metrics


def test_render_metrics_returns_prometheus_text():
    output = render_metrics()
    assert isinstance(output, (bytes, bytearray))
    text = output.decode()
    assert "nexuspanel_users" in text
    assert "nexuspanel_online_users" in text


def test_plugins_load_when_enabled():
    ff.set_flag("plugins", True)
    plugins._loaded = False
    plugins._registry.clear()
    plugins.load_plugins()
    names = {p.name for p in plugins.get_plugins()}
    assert "event_log" in names
    assert "node_alert" in names
