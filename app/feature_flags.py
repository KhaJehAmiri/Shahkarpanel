"""Feature flag system for gradual rollout and beta-gating.

Each flag has a code-defined default (see :data:`KNOWN_FLAGS`). The default can
be overridden globally or per-admin via the ``feature_flags`` table. Resolution
order for :func:`is_enabled`:

    per-admin override -> global override -> code default

Values are cached in-process and invalidated on write.
"""
import threading
from dataclasses import dataclass
from typing import Dict, Optional

from app.db import GetDB


@dataclass(frozen=True)
class FlagSpec:
    name: str
    default: bool
    description: str


# Known flags. Upcoming roadmap features register here so they can be rolled
# out gradually behind a switch instead of shipping on by default.
KNOWN_FLAGS: Dict[str, FlagSpec] = {
    f.name: f
    for f in [
        FlagSpec("prometheus_metrics", False, "Expose the Prometheus /metrics endpoint (phase 1)."),
        FlagSpec("plugins", False, "Enable the plugin system (phase 1)."),
        FlagSpec("rule_engine", False, "Enable the rule engine (phase 1)."),
        FlagSpec("auto_healing", False, "Auto-restart nodes on error/down (phase 2)."),
        FlagSpec("billing", False, "Enable billing features (phase 3)."),
        FlagSpec("api_v2", False, "Expose the v2 API (phase 3)."),
        FlagSpec("smart_routing", False, "Latency/geo/load node routing (phase 4)."),
        FlagSpec("workflows", False, "Multi-step workflow automation (phase 4)."),
        FlagSpec("traffic_intelligence", False, "Heavy/abnormal detection & prediction (phase 5)."),
        FlagSpec("plugin_marketplace", False, "Plugin marketplace & ratings (phase 5)."),
        FlagSpec("tenants", False, "White-label reseller tenants (phase 6)."),
        FlagSpec("white_label", False, "Per-tenant branding (logo/colour/title) (phase 6)."),
        FlagSpec("node_provisioning", False, "Add nodes over SSH by IP+password (phase 6)."),
        FlagSpec("tunneling", False, "In-country relay -> foreign exit tunnels (phase 6)."),
        FlagSpec("setup_wizard", True, "First-run setup wizard (phase 6)."),
    ]
}


_lock = threading.Lock()
_cache: Dict[tuple, bool] = {}


def _default(name: str) -> bool:
    spec = KNOWN_FLAGS.get(name)
    return spec.default if spec else False


def is_enabled(name: str, admin_id: Optional[int] = None) -> bool:
    """Return whether a feature flag is enabled, honouring per-admin overrides."""
    key = (name, admin_id)
    with _lock:
        if key in _cache:
            return _cache[key]

    from app.db.models import FeatureFlag

    resolved: Optional[bool] = None
    with GetDB() as db:
        if admin_id is not None:
            row = (
                db.query(FeatureFlag)
                .filter(FeatureFlag.name == name, FeatureFlag.admin_id == admin_id)
                .first()
            )
            if row is not None:
                resolved = row.enabled

        if resolved is None:
            row = (
                db.query(FeatureFlag)
                .filter(FeatureFlag.name == name, FeatureFlag.admin_id.is_(None))
                .first()
            )
            if row is not None:
                resolved = row.enabled

    if resolved is None:
        resolved = _default(name)

    with _lock:
        _cache[key] = resolved
    return resolved


def set_flag(name: str, enabled: bool, admin_id: Optional[int] = None) -> None:
    """Create or update a flag value and invalidate the cache."""
    from app.db.models import FeatureFlag

    with GetDB() as db:
        row = (
            db.query(FeatureFlag)
            .filter(FeatureFlag.name == name, FeatureFlag.admin_id == admin_id)
            .first()
        )
        if row is None:
            row = FeatureFlag(name=name, enabled=enabled, admin_id=admin_id)
            db.add(row)
        else:
            row.enabled = enabled
        db.commit()

    invalidate_cache()


def invalidate_cache() -> None:
    with _lock:
        _cache.clear()


def all_flags() -> Dict[str, bool]:
    """Resolved global value for every known flag."""
    return {name: is_enabled(name) for name in KNOWN_FLAGS}
