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
    label_key: str
    description: str = ""


KNOWN_FLAGS: Dict[str, FlagSpec] = {
    f.name: f
    for f in [
        FlagSpec(
            "prometheus_metrics",
            False,
            "flags.prometheus_metrics.desc",
            "Expose Prometheus metrics endpoint.",
        ),
        FlagSpec("plugins", False, "flags.plugins.desc", "Enable the plugin system."),
        FlagSpec("rule_engine", False, "flags.rule_engine.desc", "Enable the rule engine."),
        FlagSpec("auto_healing", False, "flags.auto_healing.desc", "Auto-restart nodes on error or down."),
        FlagSpec("billing", False, "flags.billing.desc", "Enable billing features."),
        FlagSpec(
            "user_portal",
            False,
            "flags.user_portal.desc",
            "End-user self-service portal for subscription renewal.",
        ),
        FlagSpec("api_v2", False, "flags.api_v2.desc", "Expose the v2 API."),
        FlagSpec(
            "client_api",
            False,
            "flags.client_api.desc",
            "Expose the SigmaGuard client API (auth, negotiate, config, probe).",
        ),
        FlagSpec(
            "client_ss2022",
            False,
            "flags.client_ss2022.desc",
            "Advertise Shadowsocks-2022 to clients (requires node-side inbound).",
        ),
        FlagSpec(
            "cdn_fallback",
            False,
            "flags.cdn_fallback.desc",
            "Prioritise CDN (VLESS/ws) fallback in the SigmaGuard client negotiate path.",
        ),
        FlagSpec(
            "client_push",
            False,
            "flags.client_push.desc",
            "Deliver push notifications (FCM/APNs) to SigmaGuard app devices.",
        ),
        FlagSpec("smart_routing", False, "flags.smart_routing.desc", "Latency, geo, and load-based node routing."),
        FlagSpec("workflows", False, "flags.workflows.desc", "Multi-step workflow automation."),
        FlagSpec(
            "traffic_intelligence",
            False,
            "flags.traffic_intelligence.desc",
            "Heavy usage and exhaustion prediction.",
        ),
        FlagSpec(
            "plugin_marketplace",
            False,
            "flags.plugin_marketplace.desc",
            "Plugin marketplace and ratings.",
        ),
        FlagSpec("tenants", False, "flags.tenants.desc", "White-label reseller tenants."),
        FlagSpec("white_label", False, "flags.white_label.desc", "Per-tenant branding."),
        FlagSpec(
            "node_provisioning",
            False,
            "flags.node_provisioning.desc",
            "Add nodes over SSH by IP and password.",
        ),
        FlagSpec(
            "tunneling",
            False,
            "flags.tunneling.desc",
            "Relay traffic from in-country node to foreign exit.",
        ),
        FlagSpec("setup_wizard", True, "flags.setup_wizard.desc", "First-run setup wizard."),
        FlagSpec(
            "reseller_onboarding_completed",
            False,
            "flags.reseller_onboarding.desc",
            "Reseller has finished the onboarding wizard.",
        ),
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
