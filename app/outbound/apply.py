"""Apply outbound pool presets (SOCKS/HTTP upstream + balancer + observatory)."""
from __future__ import annotations

import copy
from typing import Any

from fastapi import HTTPException

from app.outbound.presets import OUTBOUND_PRESETS

_BALANCER_STRATEGIES = frozenset({"random", "roundRobin", "leastPing", "leastLoad"})


def list_preset_ids() -> list[str]:
    return list(OUTBOUND_PRESETS.keys())


def get_preset(preset_id: str) -> dict[str, Any]:
    preset = OUTBOUND_PRESETS.get(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail=f"Unknown outbound preset '{preset_id}'")
    return preset


def _normalize_upstream(raw: dict[str, Any], *, protocol: str) -> dict[str, Any]:
    address = str(raw.get("address") or "").strip()
    if not address:
        raise HTTPException(status_code=400, detail="Each upstream requires a non-empty address")
    try:
        port = int(raw.get("port") or 0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid upstream port") from exc
    if port < 1 or port > 65535:
        raise HTTPException(status_code=400, detail="Upstream port must be 1–65535")

    server: dict[str, Any] = {"address": address, "port": port}
    user = str(raw.get("user") or raw.get("username") or "").strip()
    password = str(raw.get("pass") or raw.get("password") or "").strip()
    if user:
        server["users"] = [{"user": user, "pass": password}]
    elif password:
        server["users"] = [{"user": "", "pass": password}]
    return {"protocol": protocol, "server": server}


def build_pool_bundle(
    preset_id: str,
    *,
    upstreams: list[dict[str, Any]],
    balancer_tag: str | None = None,
    strategy: str = "leastPing",
    tag_prefix: str | None = None,
    enable_observatory: bool = True,
    probe_url: str = "https://www.google.com/generate_204",
    probe_interval: str = "10s",
) -> dict[str, Any]:
    """Build outbounds + balancer (+ optional observatory) from a preset template."""
    preset = get_preset(preset_id)
    if not upstreams:
        raise HTTPException(status_code=400, detail="At least one upstream is required")

    strategy_type = (strategy or "leastPing").strip()
    if strategy_type not in _BALANCER_STRATEGIES:
        raise HTTPException(
            status_code=400,
            detail=f"strategy must be one of: {', '.join(sorted(_BALANCER_STRATEGIES))}",
        )

    sample_out = (preset.get("outbounds") or [{}])[0]
    protocol = str(sample_out.get("protocol") or "socks")
    sample_bal = (preset.get("balancers") or [{}])[0]
    bal_tag = (balancer_tag or sample_bal.get("tag") or "upstream-pool").strip()
    if not bal_tag:
        raise HTTPException(status_code=400, detail="balancer_tag is required")

    prefix = (tag_prefix or ("socks-up" if protocol == "socks" else "http-up")).strip()
    outbounds: list[dict[str, Any]] = []
    selector: list[str] = []

    for idx, raw in enumerate(upstreams, start=1):
        norm = _normalize_upstream(raw, protocol=protocol)
        tag = f"{prefix}-{idx}"
        ob = copy.deepcopy(sample_out)
        ob["tag"] = tag
        ob["protocol"] = protocol
        ob["settings"] = {"servers": [norm["server"]]}
        outbounds.append(ob)
        selector.append(tag)

    balancer = copy.deepcopy(sample_bal)
    balancer["tag"] = bal_tag
    balancer["selector"] = selector
    balancer["strategy"] = {"type": strategy_type}

    bundle: dict[str, Any] = {
        "preset_id": preset_id,
        "outbounds": outbounds,
        "balancers": [balancer],
        "routing_rules": list(preset.get("routing") or []),
    }

    if enable_observatory and strategy_type == "leastPing":
        bundle["observatory"] = {
            "subjectSelector": selector,
            "probeUrl": probe_url or "https://www.google.com/generate_204",
            "probeInterval": probe_interval or "10s",
            "enableConcurrency": True,
        }

    return bundle


def merge_pool_bundle(
    cfg: dict[str, Any],
    bundle: dict[str, Any],
    *,
    replace_existing: bool = True,
    add_routing_rule: bool = False,
) -> dict[str, Any]:
    """Merge a pool bundle into a full Xray config dict."""
    merged = copy.deepcopy(cfg)
    routing = merged.get("routing")
    if not isinstance(routing, dict):
        routing = {}
        merged["routing"] = routing

    existing_out_tags = {str(o.get("tag") or "") for o in (merged.get("outbounds") or [])}
    existing_bal_tags = {str(b.get("tag") or "") for b in (routing.get("balancers") or [])}

    new_out_tags = {str(o.get("tag") or "") for o in bundle.get("outbounds") or []}
    new_bal_tags = {str(b.get("tag") or "") for b in bundle.get("balancers") or []}

    conflict_out = new_out_tags & existing_out_tags
    conflict_bal = new_bal_tags & existing_bal_tags
    if not replace_existing and (conflict_out or conflict_bal):
        raise HTTPException(
            status_code=409,
            detail=f"Tags already exist: out={sorted(conflict_out)} bal={sorted(conflict_bal)}",
        )

    outbounds = [o for o in (merged.get("outbounds") or []) if str(o.get("tag") or "") not in new_out_tags]
    outbounds.extend(copy.deepcopy(bundle.get("outbounds") or []))
    merged["outbounds"] = outbounds

    balancers = [b for b in (routing.get("balancers") or []) if str(b.get("tag") or "") not in new_bal_tags]
    balancers.extend(copy.deepcopy(bundle.get("balancers") or []))
    routing["balancers"] = balancers

    if bundle.get("observatory"):
        merged["observatory"] = copy.deepcopy(bundle["observatory"])

    bal_tag = str((bundle.get("balancers") or [{}])[0].get("tag") or "")
    if add_routing_rule and bal_tag:
        rules = list(routing.get("rules") or [])
        if not any(r.get("balancerTag") == bal_tag for r in rules):
            rules.insert(
                0,
                {
                    "type": "field",
                    "network": "tcp,udp",
                    "balancerTag": bal_tag,
                },
            )
            routing["rules"] = rules

    preset_rules = bundle.get("routing_rules") or []
    if preset_rules:
        rules = list(routing.get("rules") or [])
        rules.extend(copy.deepcopy(preset_rules))
        routing["rules"] = rules

    return merged
