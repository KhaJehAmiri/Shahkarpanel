"""Per-node Xray config filtering based on enabled service bindings."""
from __future__ import annotations

from copy import deepcopy
from typing import Optional, Set

from config import XRAY_EXCLUDE_INBOUND_TAGS, XRAY_FALLBACKS_INBOUND_TAG


def node_xray_inbound_tags(db, node_id: int) -> Optional[Set[str]]:
    """Return allowed product inbound tags, or ``None`` for all inbounds.

    ``None`` means the node runs every product inbound defined on the master
    (legacy behaviour and the default ``xray`` service).
    """
    from app.db import crud

    bindings = crud.get_node_service_bindings(db, node_id, enabled_only=True)
    xray_bindings = [b for b in bindings if b.service and b.service.engine == "xray"]
    if not xray_bindings:
        return None

    for b in xray_bindings:
        cfg = b.service.config or {}
        if b.service.slug == "xray" or cfg.get("mode") == "all_inbounds":
            return None
        if cfg.get("inbound_tag"):
            return {str(cfg["inbound_tag"])}

    tags: Set[str] = set()
    for b in xray_bindings:
        slug = b.service.slug
        if slug.startswith("xray-inbound-"):
            tags.add(slug[len("xray-inbound-"):])
    return tags if tags else None


def filter_xray_config_for_node(config, allowed_tags: Optional[Set[str]]):
    """Return a copy of ``config`` keeping only allowed product inbounds."""
    if allowed_tags is None:
        return config

    try:
        from app import xray

        product_tags = set(xray.config.inbounds_by_tag.keys())
    except Exception:
        product_tags = set()

    base = config.copy() if hasattr(config, "copy") else deepcopy(dict(config))
    always_keep = set(XRAY_EXCLUDE_INBOUND_TAGS or [])
    always_keep.add("API_INBOUND")
    if XRAY_FALLBACKS_INBOUND_TAG:
        always_keep.add(XRAY_FALLBACKS_INBOUND_TAG)

    filtered = []
    for inbound in base.get("inbounds") or []:
        tag = inbound.get("tag")
        if not tag or tag in always_keep or tag not in product_tags:
            filtered.append(inbound)
        elif tag in allowed_tags:
            filtered.append(inbound)
    base["inbounds"] = filtered
    return base


def apply_node_warp_policy(cfg, dbnode):
    """Apply per-node WARP exit policy on top of the filtered master config.

    - ``warp_enabled=False`` (default): strip any inherited WARP outbounds/rules
      so the node exits via ``DIRECT`` (or whatever non-WARP routing remains).
    - ``warp_enabled=True``: inject the account outbound for ``warp_tag``, make
      it the catch-all exit, point Xray-native WG at WARP, and add a dokodemo
      inbound for kernel WG/AWG TPROXY diversion.
    """
    from app.services.warp_tproxy import (
        inject_warp_tproxy_inbound,
        retarget_xray_wg_to_warp,
        strip_warp_tproxy_inbound,
    )
    from app.utils import warp as warp_util
    from app.xray.warp_routing import ensure_warp_exit, strip_warp_from_config

    raw = cfg.copy() if hasattr(cfg, "copy") else deepcopy(dict(cfg))
    data = dict(raw)
    node_id = int(getattr(dbnode, "id", 0) or 0)
    enabled = bool(getattr(dbnode, "warp_enabled", False))
    if not enabled:
        cleaned = strip_warp_from_config(data)
        if node_id:
            cleaned = strip_warp_tproxy_inbound(cleaned, node_id)
    else:
        tag = (getattr(dbnode, "warp_tag", None) or "warp").strip() or "warp"
        account = warp_util.get_warp(tag)
        outbound = (account or {}).get("outbound") if account else None
        if not isinstance(outbound, dict):
            cleaned = strip_warp_from_config(data)
            if node_id:
                cleaned = strip_warp_tproxy_inbound(cleaned, node_id)
        else:
            cleaned = ensure_warp_exit(data, outbound, as_default_exit=True)
            if node_id:
                cleaned = retarget_xray_wg_to_warp(cleaned, node_id, tag)
                cleaned = inject_warp_tproxy_inbound(cleaned, node_id, tag)

    raw.clear()
    raw.update(cleaned)
    return raw


def build_node_xray_config(node_id: int, base_config=None):
    """Master config + users, filtered for this node's Xray services."""
    from app import xray
    from app.db import GetDB
    from app.xray.operations import _apply_native_wireguard_inbound, _apply_node_tunnels

    if base_config is None:
        base_config = xray.config.include_db_users()

    with GetDB() as db:
        allowed = node_xray_inbound_tags(db, node_id)

    cfg = filter_xray_config_for_node(base_config, allowed)
    cfg = _apply_node_tunnels(cfg, node_id)
    cfg = _apply_native_wireguard_inbound(cfg, node_id)

    with GetDB() as db:
        from app.db import crud
        import commentjson

        dbnode = crud.get_node_by_id(db, node_id)
        raw = getattr(dbnode, "xray_config_override", None) if dbnode else None
        if raw:
            try:
                patch = commentjson.loads(raw)
                if isinstance(patch, dict):
                    cfg = _merge_node_override(cfg, patch)
            except Exception:
                pass
        if dbnode is not None:
            cfg = apply_node_warp_policy(cfg, dbnode)

    return cfg


def _merge_node_override(cfg, patch: dict):
    """Deep-merge a per-node override fragment into the effective config."""
    from app.xray.config import merge_dicts

    out = cfg.copy() if hasattr(cfg, "copy") else dict(cfg)
    for key in ("inbounds", "outbounds", "routing", "dns", "policy"):
        if key in patch:
            if isinstance(patch[key], list) and isinstance(out.get(key), list):
                out[key] = patch[key]
            elif isinstance(patch[key], dict):
                out[key] = merge_dicts(out.get(key) or {}, patch[key])
            else:
                out[key] = patch[key]
    return out
