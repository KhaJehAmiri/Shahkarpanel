"""SigmaGuard Wire — private bridge to /opt/sigmaguard/wire.

Not exposed on public /sub/ endpoints. Gated by feature flag ``sigmaguard_wire``.
"""
from app.sigmaguard_wire.bridge import (
    apply_preset_to_node,
    awg_params_for_node,
    build_client_conf,
    default_preset,
    is_available,
    preset_rev,
    preset_rev_for_node,
)

__all__ = [
    "apply_preset_to_node",
    "awg_params_for_node",
    "build_client_conf",
    "default_preset",
    "is_available",
    "preset_rev",
    "preset_rev_for_node",
]
