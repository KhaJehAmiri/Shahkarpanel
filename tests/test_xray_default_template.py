"""Ensure the install template does not ship production-specific data."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "xray_config.default.json"
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def test_default_xray_template_has_no_production_ips():
    raw = DEFAULT.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert data.get("inbounds") == []
    blob = json.dumps(data)
    ips = set(IPV4.findall(blob))
    allowed = {"1.1.1.1"}
    unexpected = sorted(ips - allowed)
    assert not unexpected, f"unexpected IPs in install template: {unexpected}"
    assert "91.220.8.251" not in blob


def test_default_xray_template_has_no_smoke_test_outbound():
    data = json.loads(DEFAULT.read_text(encoding="utf-8"))
    tags = [o.get("tag") for o in data.get("outbounds", [])]
    assert not any("smoke" in str(t).lower() for t in tags if t)
