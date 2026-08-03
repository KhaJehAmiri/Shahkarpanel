"""Inject Family Guard block rules into subscription client configs."""
from __future__ import annotations

import json
from typing import Any, List, Optional

import yaml

from app.family_guard.policy import is_enabled, is_pause_active
from app.family_guard.services import (
    ADS_GEOSITE,
    ADULT_GEOSITE,
    domains_for_services,
    geoips_for_services,
    geosites_for_services,
)


def collect_block_targets(controls: Optional[dict]) -> dict:
    """Return domains + geosite/geoip tags to block (empty if inactive/paused)."""
    if not is_enabled(controls) or is_pause_active(controls):
        return {"domains": [], "geosites": [], "geoips": []}
    services = list(controls.get("services") or [])
    domains = domains_for_services(services)
    for raw in controls.get("custom_domains") or []:
        d = str(raw).strip().lower().lstrip(".")
        if d and d not in domains:
            domains.append(d)
    geosites: List[str] = list(geosites_for_services(services))
    if controls.get("block_adult") and ADULT_GEOSITE not in geosites:
        geosites.append(ADULT_GEOSITE)
    if controls.get("block_ads") and ADS_GEOSITE not in geosites:
        geosites.append(ADS_GEOSITE)
    geoips: List[str] = list(geoips_for_services(services))
    return {"domains": domains, "geosites": geosites, "geoips": geoips}


def _xray_rules(domains: List[str], geosites: List[str]) -> List[dict]:
    rules: List[dict] = []
    domain_entries: List[str] = []
    for d in domains:
        domain_entries.append(f"domain:{d}")
        domain_entries.append(f"full:{d}")
    for g in geosites:
        domain_entries.append(g)
    # Chunk to keep rule size reasonable for large custom lists.
    chunk = 80
    for i in range(0, len(domain_entries), chunk):
        part = domain_entries[i : i + chunk]
        if part:
            rules.append(
                {"type": "field", "domain": part, "outboundTag": "block"}
            )
    return rules


def _ensure_xray_block_outbound(item: dict) -> None:
    outbounds = item.get("outbounds")
    if not isinstance(outbounds, list):
        item["outbounds"] = [{"protocol": "blackhole", "tag": "block"}]
        return
    if any(isinstance(o, dict) and o.get("tag") == "block" for o in outbounds):
        return
    outbounds.append({"protocol": "blackhole", "tag": "block"})


def apply_family_guard_to_json(config_text: str, controls: Optional[dict]) -> str:
    targets = collect_block_targets(controls)
    rules = _xray_rules(targets["domains"], targets["geosites"])
    if not rules:
        return config_text
    try:
        parsed = json.loads(config_text)
    except (json.JSONDecodeError, TypeError):
        return config_text
    items = parsed if isinstance(parsed, list) else [parsed]
    for item in items:
        if not isinstance(item, dict):
            continue
        _ensure_xray_block_outbound(item)
        routing = item.setdefault("routing", {})
        if not isinstance(routing, dict):
            continue
        existing = routing.get("rules")
        if not isinstance(existing, list):
            existing = []
        routing["rules"] = rules + existing
    return json.dumps(parsed, indent=2)


def apply_family_guard_to_singbox(config_text: str, controls: Optional[dict]) -> str:
    targets = collect_block_targets(controls)
    domains = targets["domains"]
    geosites = targets["geosites"]
    if not domains and not geosites:
        return config_text
    try:
        parsed = json.loads(config_text)
    except (json.JSONDecodeError, TypeError):
        return config_text
    if not isinstance(parsed, dict):
        return config_text

    # Ensure a block outbound exists.
    outbounds = parsed.get("outbounds")
    if not isinstance(outbounds, list):
        outbounds = []
        parsed["outbounds"] = outbounds
    if not any(isinstance(o, dict) and o.get("tag") == "block" for o in outbounds):
        outbounds.append({"type": "block", "tag": "block"})

    route = parsed.setdefault("route", {})
    if not isinstance(route, dict):
        route = {}
        parsed["route"] = route
    route_rules = route.get("rules")
    if not isinstance(route_rules, list):
        route_rules = []
    new_rules: List[dict] = []
    if domains:
        new_rules.append(
            {
                "domain_suffix": domains,
                "outbound": "block",
            }
        )
    rule_sets = parsed.get("rule_set")
    if not isinstance(rule_sets, list):
        rule_sets = []
    from app.routing_presets import (
        _geosite_to_singbox_rule_set_tag,
        _singbox_remote_rule_set,
    )

    for g in geosites:
        tag = _geosite_to_singbox_rule_set_tag(g)
        if not any(isinstance(r, dict) and r.get("tag") == tag for r in rule_sets):
            rule_sets.append(_singbox_remote_rule_set(tag))
        new_rules.append({"rule_set": tag, "outbound": "block"})
    parsed["rule_set"] = rule_sets
    route["rules"] = new_rules + route_rules
    return json.dumps(parsed, indent=4)


def apply_family_guard_to_clash(config_text: str, controls: Optional[dict]) -> str:
    targets = collect_block_targets(controls)
    domains = targets["domains"]
    geosites = targets["geosites"]
    if not domains and not geosites:
        return config_text
    try:
        parsed = yaml.safe_load(config_text)
    except (yaml.YAMLError, TypeError):
        return config_text
    if not isinstance(parsed, dict):
        return config_text

    rules = parsed.get("rules")
    if not isinstance(rules, list):
        rules = []
    new_rules: List[str] = []
    for d in domains:
        new_rules.append(f"DOMAIN-SUFFIX,{d},REJECT")
    for g in geosites:
        # mihomo / Clash Meta geosite rule
        name = g.split(":", 1)[-1]
        new_rules.append(f"GEOSITE,{name},REJECT")
    parsed["rules"] = new_rules + rules
    return yaml.dump(parsed, sort_keys=False, allow_unicode=True)


def apply_family_guard(
    config_text: str, config_format: str, controls: Optional[dict]
) -> str:
    if config_format == "v2ray-json":
        return apply_family_guard_to_json(config_text, controls)
    if config_format == "sing-box":
        return apply_family_guard_to_singbox(config_text, controls)
    if config_format in ("clash-meta", "clash"):
        return apply_family_guard_to_clash(config_text, controls)
    return config_text
