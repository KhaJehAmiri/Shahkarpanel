"""Fetch and compare Xray-core GitHub releases."""
from __future__ import annotations

import json
import re
import time
from typing import Optional
from urllib.error import URLError
from urllib.request import urlopen

_CACHE: dict = {"at": 0.0, "items": []}
_CACHE_TTL = 3600
_GITHUB_RELEASES_URL = (
    "https://api.github.com/repos/XTLS/Xray-core/releases?per_page=30"
)


def fetch_xray_releases(*, force: bool = False) -> list[dict]:
    now = time.time()
    if not force and now - _CACHE["at"] < _CACHE_TTL and _CACHE["items"]:
        return _CACHE["items"]
    with urlopen(_GITHUB_RELEASES_URL, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    if not isinstance(data, list):
        raise ValueError("unexpected GitHub releases payload")
    _CACHE["at"] = now
    _CACHE["items"] = data
    return data


def parse_xray_version(text: str | None) -> tuple[int, int, int] | None:
    if not text:
        return None
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def version_tuple_from_tag(tag: str | None) -> tuple[int, int, int] | None:
    if not tag:
        return None
    return parse_xray_version(tag.lstrip("vV"))


def is_version_older(current: str | None, target_tag: str) -> bool:
    cur = parse_xray_version(current) or version_tuple_from_tag(current)
    tgt = version_tuple_from_tag(target_tag)
    if tgt is None:
        return False
    if cur is None:
        return True
    return cur < tgt


def latest_xray_tag(*, include_prerelease: bool = True) -> Optional[str]:
    try:
        releases = fetch_xray_releases()
    except (URLError, OSError, json.JSONDecodeError, ValueError):
        return None
    for item in releases:
        if not include_prerelease and item.get("prerelease"):
            continue
        tag = (item.get("tag_name") or "").strip()
        if tag:
            return tag
    return None
