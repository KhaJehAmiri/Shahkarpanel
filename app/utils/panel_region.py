"""Detect whether the panel is hosted in Iran or abroad for tunnel UX hints."""
from __future__ import annotations

import json
import logging
import subprocess
from typing import Literal, Optional, Tuple
from urllib.error import URLError
from urllib.request import urlopen

from config import PANEL_REGION

logger = logging.getLogger("uvicorn.error")

PanelRegion = Literal["iran", "foreign"]
DetectedBy = Literal["env", "geoip", "manual", "default"]


def _normalize_region(raw: str) -> Optional[PanelRegion]:
    v = (raw or "").strip().lower()
    if v in ("iran", "ir", "domestic", "inside"):
        return "iran"
    if v in ("foreign", "abroad", "intl", "outside", "exit"):
        return "foreign"
    return None


def _public_ip(timeout: float = 5.0) -> Optional[str]:
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            with urlopen(url, timeout=timeout) as resp:
                ip = resp.read().decode().strip()
                if ip:
                    return ip
        except (URLError, OSError, ValueError):
            continue
    return None


def _country_code(ip: str, timeout: float = 5.0) -> Optional[str]:
    try:
        with urlopen(
            f"http://ip-api.com/json/{ip}?fields=status,countryCode",
            timeout=timeout,
        ) as resp:
            data = json.loads(resp.read().decode())
        if data.get("status") == "success":
            return (data.get("countryCode") or "").upper()
    except (URLError, OSError, ValueError, json.JSONDecodeError):
        logger.debug("GeoIP lookup failed for %s", ip, exc_info=True)
    return None


def _local_xray_version() -> Optional[str]:
    try:
        out = subprocess.check_output(
            ["/usr/local/bin/xray", "version"],
            stderr=subprocess.STDOUT,
            timeout=8,
            text=True,
        )
        for line in out.splitlines():
            if "Xray" in line:
                return line.strip()
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        pass
    return None


def _git_sha() -> Optional[str]:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL,
                timeout=5,
                text=True,
            )
            .strip()
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None


def resolve_panel_region() -> Tuple[PanelRegion, DetectedBy]:
    manual = _normalize_region(PANEL_REGION)
    if manual:
        return manual, "env"

    ip = _public_ip()
    if ip:
        cc = _country_code(ip)
        if cc == "IR":
            return "iran", "geoip"
        if cc:
            return "foreign", "geoip"

    return "foreign", "default"


def deployment_snapshot() -> dict:
    region, detected_by = resolve_panel_region()
    return {
        "panel_region": region,
        "detected_by": detected_by,
        "public_ip": _public_ip(),
        "git_sha": _git_sha(),
        "xray_local_version": _local_xray_version(),
    }


def is_iran_region(region: str) -> bool:
    return region == "iran"


def node_region_is_iran(region: Optional[str]) -> bool:
    if not region:
        return False
    r = region.strip().lower()
    return r in ("ir", "iran", "domestic")
