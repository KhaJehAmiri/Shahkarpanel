"""Region → flag + label for subscription config remarks."""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

# Region preset / ISO-ish codes used in nodes and hosts.
_REGION_META: dict[str, tuple[str, str]] = {
    "ir": ("🇮🇷", "Iran"),
    "iran": ("🇮🇷", "Iran"),
    "de": ("🇩🇪", "Germany"),
    "eu": ("🇪🇺", "Europe"),
    "us": ("🇺🇸", "United States"),
    "nl": ("🇳🇱", "Netherlands"),
    "ae": ("🇦🇪", "UAE"),
    "tr": ("🇹🇷", "Turkey"),
    "fr": ("🇫🇷", "France"),
    "fi": ("🇫🇮", "Finland"),
    "ch": ("🇨🇭", "Switzerland"),
    "be": ("🇧🇪", "Belgium"),
    "gb": ("🇬🇧", "United Kingdom"),
    "uk": ("🇬🇧", "United Kingdom"),
    "ca": ("🇨🇦", "Canada"),
    "sg": ("🇸🇬", "Singapore"),
    "jp": ("🇯🇵", "Japan"),
    "kr": ("🇰🇷", "South Korea"),
    "ru": ("🇷🇺", "Russia"),
    "custom": ("🌐", "Custom"),
}

_NAME_HINTS: tuple[tuple[str, str, str], ...] = (
    ("netherlands", "nl", "Netherlands"),
    ("belgium", "be", "Belgium"),
    ("germany", "de", "Germany"),
    ("finland", "fi", "Finland"),
    ("france", "fr", "France"),
    ("switzerland", "ch", "Switzerland"),
    ("iran", "ir", "Iran"),
    ("turkey", "tr", "Turkey"),
    ("america", "us", "United States"),
    ("united states", "us", "United States"),
)


def _normalize_key(raw: str | None) -> str:
    return (raw or "").strip().lower()


def resolve_region_display(
    region: str | None,
    *,
    node_name: str | None = None,
) -> tuple[str, str]:
    """Return (flag_emoji, human_label)."""
    key = _normalize_key(region)
    if key in _REGION_META:
        return _REGION_META[key]

    name = _normalize_key(node_name)
    if name:
        for hint, code, label in _NAME_HINTS:
            if hint in name:
                flag, _ = _REGION_META.get(code, ("🌐", label))
                return flag, label

    if key:
        return "🌐", key.upper()
    return "🌐", "Server"


def region_format_vars(
    region: str | None,
    *,
    node_name: str | None = None,
) -> dict[str, str]:
    flag, label = resolve_region_display(region, node_name=node_name)
    code = _normalize_key(region) or ""
    return {
        "REGION_FLAG": flag,
        "REGION_NAME": label,
        "REGION_CODE": code.upper() if code else "",
    }


def list_region_presets() -> list[dict[str, str]]:
    """Preset region codes for host editor (no node required)."""
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for code, (flag, name) in _REGION_META.items():
        if code in seen or code in ("iran", "custom"):
            continue
        seen.add(code)
        out.append({"code": code, "flag": flag, "name": name})
    out.sort(key=lambda x: x["name"])
    return out


@lru_cache(maxsize=1)
def panel_region_vars() -> dict[str, str]:
    from app.utils.panel_region import resolve_panel_region

    region, _ = resolve_panel_region()
    if region == "iran":
        return region_format_vars("ir")
    return region_format_vars("eu")


@lru_cache(maxsize=256)
def _db_node_region_vars(node_id: int) -> dict[str, str]:
    from app.db import GetDB, crud

    with GetDB() as db:
        dbnode = crud.get_node_by_id(db, node_id)
    if not dbnode:
        return panel_region_vars()
    return region_format_vars(dbnode.region, node_name=dbnode.name)


def region_vars_for_node(node_id: int | None) -> dict[str, str]:
    if node_id is None:
        return panel_region_vars()
    return _db_node_region_vars(int(node_id))


def parse_link_remark(link: str) -> str:
    if "#" not in link:
        return ""
    from urllib.parse import unquote

    return unquote(link.rsplit("#", 1)[-1]).strip()


def split_remark_flag(remark: str) -> tuple[str, str]:
    """Split leading flag emoji from remark title."""
    remark = (remark or "").strip()
    if not remark:
        return "", ""
    parts = remark.split(None, 1)
    first = parts[0]
    if first and ord(first[0]) > 0x1F000:
        title = parts[1] if len(parts) > 1 else ""
        return first, title.strip()
    return "", remark


# Placeholders that must never be substituted into hostnames/IPs (breaks URI parsing).
_CONNECT_VAR_BLOCKLIST = frozenset({"REGION_FLAG", "REGION_NAME", "REGION_CODE"})


def connect_format_vars(local_vars: dict) -> dict:
    """Format variables safe for address/path — no flag emoji in host part."""
    return {
        k: ("" if k in _CONNECT_VAR_BLOCKLIST else v)
        for k, v in local_vars.items()
    }


def enrich_subscription_remark(remark: str, local_vars: dict) -> str:
    """Ensure client-visible config name includes region flag + label."""
    remark = (remark or "").strip()
    flag = str(local_vars.get("REGION_FLAG") or "").strip()
    name = str(local_vars.get("REGION_NAME") or "").strip()
    if not flag:
        return remark
    existing_flag, _ = split_remark_flag(remark)
    if existing_flag:
        return remark
    prefix = f"{flag} {name}".strip()
    if not prefix:
        return remark
    return f"{prefix} · {remark}" if remark else prefix

