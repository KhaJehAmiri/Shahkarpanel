"""Post-import validation checklist for 3x-ui migration (panel.md §6)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import SubscriptionTokenAlias


@dataclass
class MigrationValidation:
    client_count: int = 0
    user_count: int = 0
    alias_count: int = 0
    hosts_count: int = 0
    inbound_count: int = 0
    passed: bool = True
    checks: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "client_count": self.client_count,
            "user_count": self.user_count,
            "alias_count": self.alias_count,
            "hosts_count": self.hosts_count,
            "inbound_count": self.inbound_count,
            "passed": self.passed,
            "checks": self.checks,
            "errors": self.errors,
        }


def _clients_from_inbound(inbound: dict) -> list[dict]:
    settings = inbound.get("settings") or {}
    if isinstance(settings, str):
        try:
            settings = json.loads(settings)
        except json.JSONDecodeError:
            settings = {}
    clients = settings.get("clients") or inbound.get("clients") or []
    return clients if isinstance(clients, list) else []


def validate_panel_import(
    db: Session,
    *,
    inbounds: list[dict],
    panel_slug: str,
    inbound_tags: list[str],
    users_created: int,
    users_updated: int,
    aliases_created: int,
    hosts_created: int,
    endpoint_id: int | None = None,
) -> MigrationValidation:
    """Run panel.md §6 checklist against a completed import."""
    result = MigrationValidation()

    clients: list[dict] = []
    sub_ids_by_uuid: dict[str, str] = {}
    for inbound in inbounds:
        for client in _clients_from_inbound(inbound):
            clients.append(client)
            uuid = str(client.get("id") or client.get("password") or client.get("uuid") or "").strip()
            sub_id = str(client.get("subId") or client.get("sub_id") or "").strip()
            if uuid and sub_id:
                prev = sub_ids_by_uuid.get(uuid)
                if prev and prev != sub_id:
                    result.errors.append(
                        f"UUID {uuid} has conflicting subId values: {prev!r} vs {sub_id!r}"
                    )
                    result.passed = False
                else:
                    sub_ids_by_uuid[uuid] = sub_id

    result.client_count = len(clients)
    result.inbound_count = len(inbound_tags)
    result.user_count = users_created + users_updated
    result.alias_count = aliases_created
    result.hosts_count = hosts_created

    expected_users = len({c.get("email") or c.get("id") for c in clients if c.get("email") or c.get("id")})
    if result.user_count < expected_users:
        result.errors.append(
            f"Expected at least {expected_users} users from backup, got {result.user_count} "
            f"(created={users_created}, updated={users_updated})"
        )
        result.passed = False
    else:
        result.checks.append(f"User count OK ({result.user_count} >= {expected_users} clients)")

    alias_clients = sum(1 for c in clients if c.get("subId") or c.get("sub_id"))
    if aliases_created < alias_clients:
        result.errors.append(
            f"Expected {alias_clients} legacy sub routes, created {aliases_created}"
        )
        result.passed = False
    else:
        result.checks.append(f"Legacy sub routes OK ({aliases_created}/{alias_clients})")

    if inbound_tags and hosts_created < len(inbound_tags):
        result.errors.append(
            f"Expected {len(inbound_tags)} migration hosts, created {hosts_created}"
        )
        result.passed = False
    elif inbound_tags:
        result.checks.append(f"ProxyHost rows OK ({hosts_created}/{len(inbound_tags)})")

    if endpoint_id is not None:
        scoped = (
            db.query(SubscriptionTokenAlias)
            .filter(SubscriptionTokenAlias.endpoint_id == endpoint_id)
            .all()
        )
        pairs = [(row.endpoint_id, row.token) for row in scoped]
        if len(pairs) != len(set(pairs)):
            result.errors.append(
                f"Duplicate (endpoint_id, sub_id) routes on panel '{panel_slug}'"
            )
            result.passed = False
        else:
            result.checks.append(
                f"Scoped sub_id routes unique for endpoint {endpoint_id} "
                "(duplicate sub_id across other panels is OK)"
            )

    if not result.errors and result.passed:
        result.checks.append(f"Panel '{panel_slug}' import validation passed")

    return result
