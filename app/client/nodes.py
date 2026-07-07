"""Per-protocol node resolution for the SigmaGuard client API."""
from typing import Dict, List, Optional

from app import client as client_engine
from app.models.node import NodeStatus


def _as_node_dict(n) -> dict:
    return {
        "id": n.id,
        "name": n.name,
        "region": n.region,
        "address": n.address,
        "latency_ms": n.latency_ms,
        "core_kind": n.core_kind,
        "role": getattr(n, "role", None),
    }


def _singbox_hy2_nodes(db, *, candidates: Optional[List] = None) -> List[dict]:
    from app.db import crud

    nodes = candidates if candidates is not None else crud.get_singbox_nodes(db)
    return [
        _as_node_dict(n)
        for n in nodes
        if n.singbox and n.singbox.hysteria2_enabled and n.status != NodeStatus.disabled
    ]


def _singbox_tuic_nodes(db, *, candidates: Optional[List] = None) -> List[dict]:
    from app.db import crud

    nodes = candidates if candidates is not None else crud.get_singbox_nodes(db)
    return [
        _as_node_dict(n)
        for n in nodes
        if n.singbox and n.singbox.tuic_enabled and n.status != NodeStatus.disabled
    ]


def _singbox_anytls_nodes(db, *, candidates: Optional[List] = None) -> List[dict]:
    from app.db import crud

    nodes = candidates if candidates is not None else crud.get_singbox_nodes(db)
    return [
        _as_node_dict(n)
        for n in nodes
        if n.singbox and n.singbox.anytls_enabled and n.status != NodeStatus.disabled
    ]


def _wireguard_nodes(db, *, candidates: Optional[List] = None) -> List[dict]:
    from app.db import crud

    nodes = candidates if candidates is not None else crud.get_wireguard_nodes(db)
    return [
        _as_node_dict(n)
        for n in nodes
        if n.wireguard is not None and n.status != NodeStatus.disabled
    ]


def _match_node(nodes: List[dict], node_id: Optional[int]) -> Optional[dict]:
    if node_id is None:
        return nodes[0] if nodes else None
    return next((n for n in nodes if n["id"] == node_id), nodes[0] if nodes else None)


def resolve_protocol_nodes(
    db,
    protocols: List[str],
    *,
    profile: str = "normal",
    probe_results: Optional[List[dict]] = None,
    bound_node_id: Optional[int] = None,
    country: Optional[str] = None,
) -> Dict[str, Optional[int]]:
    """Map each engine protocol to the best node id (or ``None`` for panel Xray)."""
    from app.db import crud

    profile = client_engine.normalize_profile(profile)
    # Fetch each candidate list once and reuse it below — this used to call
    # get_wireguard_nodes()/get_singbox_nodes() 2x/4x per request (AUDIT_FINDINGS.md M4).
    wg_candidates = crud.get_wireguard_nodes(db)
    sb_candidates = crud.get_singbox_nodes(db)
    wg_nodes = _wireguard_nodes(db, candidates=wg_candidates)
    hy2_nodes = _singbox_hy2_nodes(db, candidates=sb_candidates)
    tuic_nodes = _singbox_tuic_nodes(db, candidates=sb_candidates)
    anytls_nodes = _singbox_anytls_nodes(db, candidates=sb_candidates)
    all_nodes = wg_nodes + hy2_nodes  # for generic rank

    if profile == "trader":
        # Trader buys a dedicated IP tied to one specific node. Only protocols
        # that *node* actually serves may be pinned to it — blindly pinning
        # every protocol (including vless-reality/cdn, served from panel
        # Xray, and hysteria2/tuic/anytls, served from possibly-different
        # sing-box nodes) meant `_node_by_id()` downstream would silently
        # fall back to an arbitrary node whenever `bound_node_id` didn't
        # match, breaking the dedicated-IP guarantee without any error
        # (AUDIT_FINDINGS.md H3). Unmatched protocols get `None` — omitted
        # entirely rather than served from the wrong node.
        wg_ids = {n["id"] for n in wg_nodes}
        hy2_ids = {n["id"] for n in hy2_nodes}
        tuic_ids = {n["id"] for n in tuic_nodes}
        anytls_ids = {n["id"] for n in anytls_nodes}

        def _pin_if_capable(ids: set) -> Optional[int]:
            return bound_node_id if bound_node_id is not None and bound_node_id in ids else None

        mapping: Dict[str, Optional[int]] = {}
        for proto in protocols:
            if proto in ("wireguard", "amneziawg"):
                mapping[proto] = _pin_if_capable(wg_ids)
            elif proto == "hysteria2":
                mapping[proto] = _pin_if_capable(hy2_ids)
            elif proto == "tuic":
                mapping[proto] = _pin_if_capable(tuic_ids)
            elif proto == "anytls":
                mapping[proto] = _pin_if_capable(anytls_ids)
            else:
                # sigmaguard-wire piggybacks on the amneziawg pin in
                # app/client/materials.py; vless-reality / ss-2022 / cdn are
                # panel-Xray-served and never node-pinned.
                mapping[proto] = None
        return mapping

    use_country = country if (country or profile == "gamer") else None
    ranked_wg = client_engine.rank_nodes(wg_nodes, probe_results, country=use_country)
    ranked_hy2 = client_engine.rank_nodes(hy2_nodes, probe_results, country=use_country)
    ranked_tuic = client_engine.rank_nodes(tuic_nodes, probe_results, country=use_country)
    ranked_anytls = client_engine.rank_nodes(anytls_nodes, probe_results, country=use_country)
    ranked_any = client_engine.rank_nodes(all_nodes, probe_results, country=use_country)
    default_id = ranked_any[0]["id"] if ranked_any else None

    mapping: Dict[str, Optional[int]] = {}
    for proto in protocols:
        if proto in ("wireguard", "amneziawg"):
            mapping[proto] = ranked_wg[0]["id"] if ranked_wg else default_id
        elif proto == "hysteria2":
            mapping[proto] = ranked_hy2[0]["id"] if ranked_hy2 else default_id
        elif proto == "tuic":
            mapping[proto] = ranked_tuic[0]["id"] if ranked_tuic else default_id
        elif proto == "anytls":
            mapping[proto] = ranked_anytls[0]["id"] if ranked_anytls else default_id
        else:
            # vless-reality / ss-2022 / cdn are served from panel Xray hosts.
            mapping[proto] = None
    return mapping


def tunnel_hint(db) -> dict:
    """Summarise relay→exit tunnel availability for the app."""
    from app import feature_flags
    from app.db.models import Tunnel

    if not feature_flags.is_enabled("tunneling"):
        return {
            "available": False,
            "active_count": 0,
            "topology": "direct",
            "tunnels": [],
        }
    rows = db.query(Tunnel).filter(Tunnel.enabled.is_(True)).all()
    tunnels = [
        {
            "id": t.id,
            "name": t.name,
            "transport": t.transport,
            "relay_node_id": t.relay_node_id,
            "exit_node_id": t.exit_node_id,
        }
        for t in rows
    ]
    return {
        "available": bool(tunnels),
        "active_count": len(tunnels),
        "topology": "relay_exit" if tunnels else "direct",
        "tunnels": tunnels,
        "hint": (
            "Traffic may enter via an in-country relay and exit abroad."
            if tunnels
            else "Direct node connection."
        ),
    }
