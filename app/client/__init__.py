"""SigmaGuard client engine (phase A).

Pure, dependency-free logic for the mobile/desktop client API:

* protocol negotiation — which protocols are usable on a given network for a
  given user profile, ordered by priority;
* node ranking — order candidate nodes by measured/known latency and loss.

Kept free of DB and FastAPI imports so it is trivially unit-testable. The
router (`app/routers/client_v2.py`) adapts DB rows into the plain dicts these
functions consume.
"""
from typing import Dict, List, Optional

PROFILES = ("gamer", "trader", "normal")
NETWORKS = ("open", "restricted", "heavily_restricted")

# Full protocol catalog the client understands.
ALL_PROTOCOLS: List[str] = [
    "amneziawg",
    "hysteria2",
    "tuic",
    "vless-reality",
    "shadowsocks-2022",
    "wireguard",
    "cdn",
]

# Protocols that require UDP to function.
UDP_PROTOCOLS = frozenset({"amneziawg", "hysteria2", "tuic", "wireguard"})

# Protocols that survive heavy DPI (look like ordinary TLS/HTTPS).
CAMOUFLAGED = frozenset({"vless-reality", "cdn"})

# Per-profile priority (highest first), from the product brief.
PROFILE_PRIORITY: Dict[str, List[str]] = {
    "gamer": ["amneziawg", "hysteria2", "vless-reality"],
    "trader": ["vless-reality"],
    "normal": ["vless-reality", "shadowsocks-2022", "cdn"],
}

# Network-appropriate fallbacks appended after the profile's own priority.
_NETWORK_EXTRAS: Dict[str, List[str]] = {
    "open": ["wireguard", "amneziawg", "hysteria2", "tuic", "vless-reality", "shadowsocks-2022"],
    "restricted": ["vless-reality", "hysteria2", "tuic", "shadowsocks-2022", "amneziawg", "cdn"],
    "heavily_restricted": ["vless-reality", "cdn"],
}


def normalize_profile(profile: Optional[str]) -> str:
    return profile if profile in PROFILE_PRIORITY else "normal"


def normalize_network(net: Optional[str]) -> str:
    return net if net in NETWORKS else "open"


def _is_blocked(protocol: str, net: str, udp: bool) -> bool:
    if not udp and protocol in UDP_PROTOCOLS:
        return True
    if net == "heavily_restricted" and protocol not in CAMOUFLAGED:
        return True
    return False


def negotiate(
    profile: str = "normal",
    net: str = "open",
    udp: bool = True,
    available: Optional[set] = None,
    cdn_fallback: bool = False,
) -> dict:
    """Return usable/blocked protocols (ordered) for the network + profile.

    Trader never auto-switches: it is pinned to a single camouflaged protocol.

    ``available`` — when provided, only protocols the panel can actually serve
    are advertised. Anything outside the set is moved to ``blocked_protocols``
    so the client never tries a protocol the backend can't deliver. ``None``
    means "do not filter by availability" (e.g. unit tests).
    """
    profile = normalize_profile(profile)
    net = normalize_network(net)
    avail = set(available) if available is not None else None

    if profile == "trader":
        ordered = ["vless-reality"]
    else:
        base = list(PROFILE_PRIORITY[profile])
        cdn_ok = avail is None or "cdn" in avail
        if cdn_fallback and profile == "normal" and cdn_ok:
            base = ["vless-reality", "cdn"] + [p for p in base if p not in ("vless-reality", "cdn")]
        extras = _NETWORK_EXTRAS[net]
        ordered = base + [p for p in extras if p not in base]

    usable = [
        p for p in ordered
        if not _is_blocked(p, net, udp) and (avail is None or p in avail)
    ]
    if not usable:
        # Reality is the guaranteed camouflaged fallback — but only if the
        # panel actually serves it; otherwise pick any available protocol.
        if avail is None or "vless-reality" in avail:
            usable = ["vless-reality"]
        else:
            usable = [p for p in ALL_PROTOCOLS if p in avail][:1]

    blocked = [
        p for p in ALL_PROTOCOLS
        if _is_blocked(p, net, udp) or (avail is not None and p not in avail)
    ]

    return {
        "profile": profile,
        "net": net,
        "udp": udp,
        "usable_protocols": usable,
        "blocked_protocols": blocked,
        "recommended": usable[0] if usable else None,
    }


_REGION_HINTS = {
    "IR": ("IR", "IRAN", "ME", "MIDDLE"),
    "DE": ("DE", "EU", "EUROPE", "GER", "GERMANY"),
    "NL": ("NL", "EU", "EUROPE", "NETHER"),
    "US": ("US", "NA", "AMERICA"),
    "TR": ("TR", "TURKEY", "TUR"),
}


def _country_region_bonus(node: dict, country: Optional[str]) -> float:
    """Negative bonus lowers score (preferred) when region matches country."""
    if not country:
        return 0.0
    cc = country.strip().upper()
    region = (node.get("region") or "").upper()
    if not region:
        return 0.0
    if cc in region or region.startswith(cc) or region.endswith(cc):
        return -80.0
    for hint in _REGION_HINTS.get(cc, (cc,)):
        if hint in region:
            return -80.0
    return 0.0


def _node_score(
    node: dict,
    probe_by_node: Dict[int, dict],
    country: Optional[str] = None,
) -> float:
    """Lower is better. Measured probe beats the node's last known latency."""
    probe = probe_by_node.get(node.get("id"))
    if probe is not None:
        ping = probe.get("ping_ms")
        loss = probe.get("packet_loss_pct") or 0.0
    else:
        ping = node.get("latency_ms")
        loss = 0.0
    if ping is None:
        ping = 9999.0
    return float(ping) + float(loss) * 20.0 + _country_region_bonus(node, country)


def rank_nodes(
    nodes: List[dict],
    probe_results: Optional[List[dict]] = None,
    country: Optional[str] = None,
) -> List[dict]:
    """Order nodes best-first by latency, loss, and optional country/region."""
    probe_by_node: Dict[int, dict] = {}
    for r in probe_results or []:
        nid = r.get("node_id")
        if nid is not None:
            prev = probe_by_node.get(nid)
            if prev is None or _sample_score(r) < _sample_score(prev):
                probe_by_node[nid] = r
    return sorted(nodes, key=lambda n: _node_score(n, probe_by_node, country))


def _sample_score(sample: dict) -> float:
    ping = sample.get("ping_ms")
    loss = sample.get("packet_loss_pct") or 0.0
    if ping is None:
        ping = 9999.0
    return float(ping) + float(loss) * 20.0


def select_nodes(
    nodes: List[dict],
    profile: str = "normal",
    probe_results: Optional[List[dict]] = None,
    bound_node_id: Optional[int] = None,
    country: Optional[str] = None,
) -> dict:
    """Pick recommended + fallback node ids for a profile.

    Trader is pinned to ``bound_node_id`` (its dedicated IP) and never gets a
    fallback — the client must not migrate.
    """
    profile = normalize_profile(profile)

    if profile == "trader":
        chosen = next((n for n in nodes if n.get("id") == bound_node_id), None)
        return {
            "recommended_node": chosen["id"] if chosen else None,
            "fallback_node": None,
        }

    use_country = country if (country or profile == "gamer") else None
    ranked = rank_nodes(nodes, probe_results, country=use_country)
    if not ranked:
        return {"recommended_node": None, "fallback_node": None}
    return {
        "recommended_node": ranked[0].get("id"),
        "fallback_node": ranked[1].get("id") if len(ranked) > 1 else None,
    }
