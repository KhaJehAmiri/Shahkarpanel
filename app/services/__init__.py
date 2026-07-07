"""Centralized service catalog and node enablement."""
from app.services.catalog import SERVICE_SEEDS, SINGBOX_SLUGS, WIREGUARD_SLUGS
from app.services.materialize import materialize_node_services, provision_slug_list
from app.services.node_apply import apply_node_services, apply_services_after_provision, set_node_services
from app.services.node_pick import pick_node
from app.services.xray_node import build_node_xray_config, filter_xray_config_for_node, node_xray_inbound_tags

__all__ = [
    "SERVICE_SEEDS",
    "SINGBOX_SLUGS",
    "WIREGUARD_SLUGS",
    "materialize_node_services",
    "provision_slug_list",
    "apply_node_services",
    "apply_services_after_provision",
    "set_node_services",
    "pick_node",
    "build_node_xray_config",
    "filter_xray_config_for_node",
    "node_xray_inbound_tags",
]
