"""Fleet-wide egress blocking: BitTorrent, malware/phishing, abuse C2, piracy hosts.

Injected into every Xray rebuild (panel + nodes) beside Family Guard. Rules are
marked ``shahkarEgressGuard`` so rebuilds can strip/replace without touching
operator or Family Guard rules.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

# Marker so rebuilds can strip previous egress-guard rules.
RULE_MARK = "shahkarEgressGuard"
_OUTBOUND = "BLOCK"
_CHUNK = 48

# Geosite packs present in the panel's geosite.dat (v2fly/Loyalsoldier subset).
GEOSITE_BLOCKS: Sequence[str] = (
    "geosite:malware",
    "geosite:phishing",
)

# Explicit domains — badbox2 C2 from NCSC/Shadowserver + common piracy/trackers.
# Kept as domain: suffixes so subdomains match.
ABUSE_AND_PIRACY_DOMAINS: Sequence[str] = (
    # NCSC android.badbox2 sinkhole / C2 referrers (Aug 2026)
    "holadns.com",
    "martianinc.co",
    # Common torrent indexes / trackers (complement protocol sniff)
    "thepiratebay.org",
    "piratebay.org",
    "1337x.to",
    "rarbg.to",
    "rarbgproxied.org",
    "yts.mx",
    "yts.lt",
    "eztv.re",
    "torrentgalaxy.to",
    "torrentleech.org",
    "nyaa.si",
    "sukebei.nyaa.si",
    "rutracker.org",
    "rutracker.net",
    "nnmclub.to",
    "limetorrents.pro",
    "torlock.com",
    "zooqle.com",
    "kickasstorrents.to",
    "katcr.co",
    "magnetdl.com",
    "ilovetrackers.com",
    "openbittorrent.com",
    "opentrackr.org",
    "tracker.opentrackr.org",
    "exodus.desync.com",
    "tracker.openbittorrent.com",
    "coppersurfer.tk",
    "leechers-paradise.org",
)


def is_enabled() -> bool:
    """Default ON — operators can disable via platform setting."""
    try:
        from app import platform_settings as ps

        return bool(ps.get_bool("security.egress_guard_enabled", True))
    except Exception:
        return True


def _domain_entries(domains: Sequence[str]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for d in domains:
        d = str(d).strip().lower().lstrip(".")
        if not d or d in seen:
            continue
        seen.add(d)
        out.append(f"domain:{d}")
        out.append(f"full:{d}")
    return out


def build_egress_guard_rules() -> List[dict]:
    """Build Xray routing rules for fleet egress policy."""
    rules: List[dict] = []

    # Protocol sniff (requires inbound sniffing enabled; not destOverride).
    rules.append(
        {
            "type": "field",
            "protocol": ["bittorrent"],
            "outboundTag": _OUTBOUND,
            RULE_MARK: True,
        }
    )

    geosites = [g for g in GEOSITE_BLOCKS if g]
    if geosites:
        rules.append(
            {
                "type": "field",
                "domain": list(geosites),
                "outboundTag": _OUTBOUND,
                RULE_MARK: True,
            }
        )

    domain_entries = _domain_entries(ABUSE_AND_PIRACY_DOMAINS)
    for i in range(0, len(domain_entries), _CHUNK):
        part = domain_entries[i : i + _CHUNK]
        if not part:
            continue
        rules.append(
            {
                "type": "field",
                "domain": part,
                "outboundTag": _OUTBOUND,
                RULE_MARK: True,
            }
        )
    return rules


def strip_egress_guard_rules(rules: Optional[List[Any]]) -> List[Any]:
    if not isinstance(rules, list):
        return []
    return [
        r
        for r in rules
        if not (isinstance(r, dict) and r.get(RULE_MARK))
    ]


def ensure_inbound_sniffing(config: Dict[str, Any]) -> None:
    """Enable sniffing on non-WG inbounds so ``protocol: bittorrent`` can match.

    Does **not** rewrite ``domainStrategy`` or force ``IPIfNonMatch`` (latency).
    Does **not** put ``bittorrent`` into ``destOverride`` (Xray rejects it there).
    """
    inbounds = config.get("inbounds")
    if not isinstance(inbounds, list):
        return
    for inbound in inbounds:
        if not isinstance(inbound, dict):
            continue
        proto = str(inbound.get("protocol") or "").lower()
        if proto in ("wireguard", "tun", "dokodemo-door"):
            # dokodemo may still want sniffing when used as entry; keep WG clean.
            if proto == "wireguard":
                continue
        sniff = inbound.get("sniffing")
        if not isinstance(sniff, dict):
            sniff = {}
            inbound["sniffing"] = sniff
        sniff["enabled"] = True
        dest = sniff.get("destOverride")
        if not isinstance(dest, list) or not dest:
            sniff["destOverride"] = ["http", "tls", "quic"]
        else:
            # Drop invalid bittorrent from destOverride if present.
            cleaned = [
                str(x).strip().lower()
                for x in dest
                if str(x).strip().lower() in ("http", "tls", "quic", "fakedns")
            ]
            sniff["destOverride"] = cleaned or ["http", "tls", "quic"]
        # Prefer metadata sniff so protocol detection works without full redirect.
        if "routeOnly" not in sniff:
            sniff["routeOnly"] = True


def apply_egress_guard_routing(config: Dict[str, Any]) -> Dict[str, Any]:
    """Mutate ``config`` routing: replace fleet egress-guard rules."""
    routing = config.get("routing")
    if not isinstance(routing, dict):
        routing = {"domainStrategy": "AsIs", "rules": []}
        config["routing"] = routing
    existing = routing.get("rules")
    if not isinstance(existing, list):
        existing = []

    kept = strip_egress_guard_rules(existing)

    if not is_enabled():
        routing["rules"] = kept
        return config

    # Ensure BLOCK outbound exists (blackhole).
    outbounds = config.get("outbounds")
    if isinstance(outbounds, list):
        tags = {
            str(o.get("tag") or "").upper()
            for o in outbounds
            if isinstance(o, dict)
        }
        if "BLOCK" not in tags:
            outbounds.append(
                {"tag": "BLOCK", "protocol": "blackhole", "settings": {}}
            )

    ensure_inbound_sniffing(config)
    eg_rules = build_egress_guard_rules()
    # Prepend so blocks win over catch-all DIRECT rules.
    routing["rules"] = eg_rules + kept
    return config
