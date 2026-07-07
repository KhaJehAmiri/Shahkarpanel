"""Cross-panel UUID collision detection (panel.md §6.0)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class UuidCollision:
    uuid: str
    first_panel: str
    second_panel: str

    def to_dict(self) -> dict[str, str]:
        return {
            "type": "uuid_shared_across_servers",
            "uuid": self.uuid,
            "first_panel": self.first_panel,
            "second_panel": self.second_panel,
        }


@dataclass
class CollisionReport:
    collisions: list[UuidCollision] = field(default_factory=list)

    @property
    def has_conflicts(self) -> bool:
        return bool(self.collisions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_conflicts": self.has_conflicts,
            "collisions": [c.to_dict() for c in self.collisions],
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


def detect_uuid_collisions(exports: list[tuple[str, list[dict]]]) -> CollisionReport:
    """Detect UUIDs shared across independent 3x-ui panels (panel.md §6.0).

    Duplicate ``sub_id`` across panels is expected and **not** reported here.
    """
    seen: dict[str, str] = {}
    report = CollisionReport()
    for panel_slug, inbounds in exports:
        for inbound in inbounds:
            for client in _clients_from_inbound(inbound):
                uid = str(
                    client.get("id") or client.get("password") or client.get("uuid") or ""
                ).strip()
                if not uid:
                    continue
                prev = seen.get(uid)
                if prev and prev != panel_slug:
                    report.collisions.append(
                        UuidCollision(uuid=uid, first_panel=prev, second_panel=panel_slug)
                    )
                else:
                    seen[uid] = panel_slug
    return report
