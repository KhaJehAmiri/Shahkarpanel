"""Sing-box inbound registry for the Inbounds hub (TUIC / AnyTLS on nodes)."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

from app.db import crud
from app.db.models import Node
from app.tls.acme import DEFAULT_CERT, DEFAULT_KEY
from app.xray.inbound_presets import INBOUND_PRESETS

SingboxProtocol = Literal["tuic", "anytls"]


def _preset_or_404(preset_id: str) -> dict[str, Any]:
    preset = INBOUND_PRESETS.get(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail=f"Unknown inbound preset '{preset_id}'")
    if preset.get("deploy") != "singbox":
        raise HTTPException(status_code=400, detail=f"Preset '{preset_id}' is not a sing-box inbound")
    return preset


def preset_protocol(preset_id: str) -> SingboxProtocol:
    preset = _preset_or_404(preset_id)
    proto = str(preset.get("protocol") or "")
    if proto not in ("tuic", "anytls"):
        raise HTTPException(status_code=400, detail=f"Preset '{preset_id}' has no sing-box protocol")
    return proto  # type: ignore[return-value]


def list_singbox_inbound_entries(db: Session) -> list[dict[str, Any]]:
    """Virtual inbound rows for every enabled TUIC/AnyTLS on a node."""
    nodes = (
        db.query(Node)
        .options(joinedload(Node.singbox))
        .order_by(Node.id)
        .all()
    )
    entries: list[dict[str, Any]] = []
    for node in nodes:
        sb = node.singbox
        if sb is None:
            continue
        base = {
            "node_id": node.id,
            "node_name": node.name,
            "node_address": node.address,
            "node_status": node.status,
            "engine": "singbox",
            "tls_trusted": bool(sb.tls_trusted),
            "sni": sb.sni or node.address,
        }
        if sb.tuic_enabled and sb.tuic_port:
            entries.append(
                {
                    **base,
                    "id": f"node-{node.id}-tuic",
                    "preset_id": "tuic-inbound",
                    "protocol": "tuic",
                    "tag": "tuic-in",
                    "port": int(sb.tuic_port),
                    "transport": "quic",
                    "security": "tls",
                    "congestion_control": sb.tuic_congestion_control or "bbr",
                }
            )
        if sb.anytls_enabled and sb.anytls_port:
            entries.append(
                {
                    **base,
                    "id": f"node-{node.id}-anytls",
                    "preset_id": "anytls-inbound",
                    "protocol": "anytls",
                    "tag": "anytls-in",
                    "port": int(sb.anytls_port),
                    "transport": "tcp",
                    "security": "tls",
                }
            )
    return entries


def _ensure_singbox_row(db: Session, dbnode: Node):
    cfg = crud.get_node_singbox(db, dbnode)
    if cfg is not None:
        return cfg
    return crud.provision_singbox_defaults(
        db,
        dbnode,
        hysteria2=False,
        tuic=False,
        sni=(dbnode.address or "").strip() or None,
    )


def apply_singbox_inbound_preset(
    db: Session,
    preset_id: str,
    *,
    node_id: int,
    port: int | None = None,
    tuic_congestion_control: str | None = None,
) -> dict[str, Any]:
    """Enable TUIC or AnyTLS on a node and return the virtual inbound entry."""
    preset = _preset_or_404(preset_id)
    proto = preset_protocol(preset_id)

    dbnode = crud.get_node_by_id(db, node_id)
    if dbnode is None:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")

    cfg = _ensure_singbox_row(db, dbnode)
    updates: dict[str, Any] = {}

    if not cfg.certificate_path:
        updates["certificate_path"] = DEFAULT_CERT
    if not cfg.key_path:
        updates["key_path"] = DEFAULT_KEY
    if not (cfg.sni or "").strip():
        updates["sni"] = (dbnode.address or "").strip()

    default_port = int(preset.get("default_port") or (44334 if proto == "tuic" else 44335))
    listen_port = int(port or default_port)
    if listen_port < 1 or listen_port > 65535:
        raise HTTPException(status_code=400, detail="port must be 1–65535")

    if proto == "tuic":
        updates.update(
            {
                "tuic_enabled": True,
                "tuic_port": listen_port,
                "tuic_congestion_control": (tuic_congestion_control or "bbr").strip() or "bbr",
            }
        )
    else:
        updates.update({"anytls_enabled": True, "anytls_port": listen_port})

    crud.upsert_node_singbox(db, dbnode, **updates)
    db.refresh(dbnode)

    entries = [e for e in list_singbox_inbound_entries(db) if e["node_id"] == node_id and e["protocol"] == proto]
    if not entries:
        raise HTTPException(status_code=500, detail="Failed to register sing-box inbound after save")

    return {
        "node_id": node_id,
        "preset_id": preset_id,
        "protocol": proto,
        "inbound": entries[0],
    }


def disable_singbox_inbound(db: Session, node_id: int, protocol: SingboxProtocol) -> dict[str, Any]:
    dbnode = crud.get_node_by_id(db, node_id)
    if dbnode is None:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")
    if protocol == "tuic":
        crud.upsert_node_singbox(db, dbnode, tuic_enabled=False, tuic_port=None)
    else:
        crud.upsert_node_singbox(db, dbnode, anytls_enabled=False, anytls_port=None)
    return {"node_id": node_id, "protocol": protocol, "disabled": True}
