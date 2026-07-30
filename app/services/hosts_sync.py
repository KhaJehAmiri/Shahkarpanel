"""Keep subscription hosts in sync when Xray services are enabled on a node."""
from __future__ import annotations

import logging

from app.models.proxy import ProxyHost

logger = logging.getLogger("shahkar-services-hosts")


def sync_hosts_for_node(db, dbnode, *, xray_enabled: bool = True) -> int:
    """Ensure the node's address appears in hosts for each product inbound.

    Returns the number of new host rows created.
    """
    if not xray_enabled or not dbnode.address:
        return 0

    from app import xray
    from app.db import crud

    created = 0
    addr = dbnode.address.strip()
    remark = f"{dbnode.name} ({{USERNAME}}) [{{PROTOCOL}} - {{TRANSPORT}}]"

    for inbound_tag in xray.config.inbounds_by_tag:
        existing = crud.get_hosts(db, inbound_tag)
        if any(addr in (h.address or "") for h in existing):
            continue
        crud.add_host(
            db,
            inbound_tag,
            ProxyHost(remark=remark, address=addr),
        )
        created += 1

    if created:
        try:
            xray.hosts.update()
        except Exception as exc:
            logger.warning("hosts cache refresh failed: %s", exc)
    return created
