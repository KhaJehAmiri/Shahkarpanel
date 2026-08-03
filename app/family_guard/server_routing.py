"""Server-side Family Guard routing for the panel/node Xray cores.

Client subscription formats that are only share-link lists (``v2ray`` /
``vless://``) cannot carry domain block rules. Injecting ``user`` + ``domain``
/ ``ip`` rules into the live core makes blocks work regardless of which client
app the child uses.

Performance notes:
* Do **not** rewrite global ``domainStrategy`` (``IPIfNonMatch`` forces DNS on
  every unmatched flow and tanks latency for all users).
* Do **not** mutate inbound sniffing for the whole core — keep each inbound's
  existing sniffing; domain rules still match when SNI is available.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.family_guard.apply import collect_block_targets
from app.family_guard.policy import is_enabled

# Marker so rebuilds can strip previous Family Guard rules without touching
# unrelated BLOCK rules (private IP, etc.). Xray ignores unknown JSON fields.
_RULE_MARK = "shahkarFamilyGuard"
_OUTBOUND = "BLOCK"
_CHUNK = 64


def xray_user_email(user_id: int, username: str) -> str:
    """Match the email format ``include_db_users`` writes into inbound clients."""
    return f"{user_id}.{username}"


def _domain_entries(domains: Sequence[str]) -> List[str]:
    out: List[str] = []
    for d in domains:
        d = str(d).strip().lower().lstrip(".")
        if not d:
            continue
        out.append(f"domain:{d}")
        out.append(f"full:{d}")
    return out


def build_family_guard_rules(
    users: Iterable[Tuple[int, str, Optional[dict]]],
) -> List[dict]:
    """Build Xray routing rules for active Family Guard domain/geosite/geoip blocks."""
    rules: List[dict] = []
    for user_id, username, controls in users:
        if not isinstance(controls, dict) or not is_enabled(controls):
            continue
        targets = collect_block_targets(controls)
        domains = targets.get("domains") or []
        geosites = targets.get("geosites") or []
        geoips = targets.get("geoips") or []
        if not domains and not geosites and not geoips:
            continue
        email = xray_user_email(int(user_id), str(username))
        # Prefer geosite tags (compact) over huge domain lists when both exist.
        entries: List[str] = []
        for g in geosites:
            g = str(g).strip()
            if g:
                entries.append(g if g.startswith("geosite:") else f"geosite:{g}")
        # Only add explicit domains that are not already covered by a geosite pack
        # when no geosite was set — keeps rule tables small.
        if not geosites:
            entries.extend(_domain_entries(domains))
        else:
            # Keep a short domain supplement (custom-style extras already merged
            # into domains); cap to avoid megabyte routing tables.
            extras = _domain_entries(domains[:24])
            entries.extend(extras)
        for i in range(0, len(entries), _CHUNK):
            part = entries[i : i + _CHUNK]
            if not part:
                continue
            rules.append(
                {
                    "type": "field",
                    "user": [email],
                    "domain": part,
                    "outboundTag": _OUTBOUND,
                    _RULE_MARK: True,
                }
            )
        ip_entries: List[str] = []
        for g in geoips:
            g = str(g).strip()
            if not g:
                continue
            ip_entries.append(g if g.startswith("geoip:") else f"geoip:{g}")
        if ip_entries:
            rules.append(
                {
                    "type": "field",
                    "user": [email],
                    "ip": ip_entries,
                    "outboundTag": _OUTBOUND,
                    _RULE_MARK: True,
                }
            )
    return rules


def strip_family_guard_rules(rules: Optional[List[Any]]) -> List[Any]:
    if not isinstance(rules, list):
        return []
    return [
        r
        for r in rules
        if not (isinstance(r, dict) and r.get(_RULE_MARK))
    ]


def apply_family_guard_server_routing(config: Dict[str, Any], db) -> Dict[str, Any]:
    """Mutate ``config`` routing: replace Family Guard rules from DB users."""
    from app.db import models as db_models
    from app.models.user import UserStatus

    routing = config.get("routing")
    if not isinstance(routing, dict):
        routing = {"domainStrategy": "AsIs", "rules": []}
        config["routing"] = routing
    existing = routing.get("rules")
    if not isinstance(existing, list):
        existing = []

    kept = strip_family_guard_rules(existing)

    rows = (
        db.query(db_models.User.id, db_models.User.username, db_models.User.family_controls)
        .filter(
            db_models.User.status.in_([UserStatus.active, UserStatus.on_hold]),
            db_models.User.family_controls.isnot(None),
        )
        .all()
    )
    fg_rules = build_family_guard_rules(
        (row.id, row.username, row.family_controls) for row in rows
    )

    # Only prepend per-user block rules. Never touch sniffing or domainStrategy —
    # those are fleet-wide and destroy latency for everyone.
    routing["rules"] = fg_rules + kept
    return config


def family_block_fingerprint(controls: Optional[dict]) -> Tuple:
    """Stable digest of what the core must enforce (for change detection)."""
    if not isinstance(controls, dict) or not is_enabled(controls):
        return ()
    targets = collect_block_targets(controls)
    return (
        tuple(targets.get("domains") or []),
        tuple(targets.get("geosites") or []),
        tuple(targets.get("geoips") or []),
    )
