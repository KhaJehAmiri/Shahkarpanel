"""Post-SSH steps after the node agent registers (sing-box, TLS, tunnel)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from app import provisioning
from app.db import GetDB, crud
from app.models.node import CoreKind
from app.tls.acme import DEFAULT_CERT, DEFAULT_KEY, issue_certificate, normalize_tls_target
from app.tls.self_signed import install_self_signed
from app.utils.panel_region import node_region_is_iran

logger = logging.getLogger("nexus-provision")


@dataclass
class ProvisionExtras:
    enable_hysteria2: bool = True
    enable_tuic: bool = False
    enable_anytls: bool = False
    tls_mode: str = "self_signed"  # self_signed | letsencrypt | none
    le_target: Optional[str] = None
    le_email: Optional[str] = None
    le_kind: str = "auto"
    create_tunnel: bool = False
    tunnel_port: int = 443
    region: Optional[str] = None
    enable_plain_wg_on_xray: bool = False
    enable_awg_on_xray: bool = False
    enable_awg_wg: bool = False


def _sync_singbox(node_id: int) -> None:
    try:
        from app.singbox.operations import sync_node

        with GetDB() as db:
            dbnode = crud.get_node_by_id(db, node_id)
            if dbnode and dbnode.singbox:
                sync_node(db, dbnode)
    except Exception as exc:
        logger.warning("Post-provision sing-box sync failed for node %s: %s", node_id, exc)


def _maybe_create_tunnel(db, dbnode, extras: ProvisionExtras) -> None:
    if not extras.create_tunnel:
        return
    from app.db.models import Tunnel
    from app.tunnel import default_params, ensure_reality_keys, validate_transport

    existing = (
        db.query(Tunnel)
        .filter(
            (Tunnel.relay_node_id == dbnode.id) | (Tunnel.exit_node_id == dbnode.id),
        )
        .first()
    )
    if existing:
        return

    transport = "reality"
    validate_transport(transport)
    params = default_params(transport)
    ensure_reality_keys(params)
    port = int(extras.tunnel_port or 443)
    region = extras.region or dbnode.region
    is_iran = node_region_is_iran(region)

    if is_iran:
        tunnel = Tunnel(
            name=f"{dbnode.name}-to-panel",
            relay_node_id=dbnode.id,
            exit_node_id=None,
            transport=transport,
            listen_port=port,
            target_port=port,
            params=params,
        )
        dbnode.role = "relay"
    else:
        tunnel = Tunnel(
            name=f"panel-to-{dbnode.name}",
            relay_node_id=None,
            exit_node_id=dbnode.id,
            transport=transport,
            listen_port=port,
            target_port=port,
            params=params,
        )
        dbnode.role = "exit"

    tunnel.enabled = True
    db.add(tunnel)
    db.commit()
    db.refresh(tunnel)
    _apply_tunnel(db, tunnel)
    logger.info("Post-provision tunnel %s created and applied for node %s", tunnel.name, dbnode.id)


def _apply_tunnel(db, tunnel) -> None:
    """Push tunnel config to relay/exit endpoints (panel or nodes)."""
    from app import xray

    endpoints = {tunnel.relay_node_id, tunnel.exit_node_id}
    for node_id in endpoints:
        try:
            if node_id is None:
                xray.core.restart(xray.config.include_db_users())
            else:
                node = xray.nodes.get(node_id)
                if node is not None and getattr(node, "connected", False):
                    xray.operations.restart_node(node_id)
                else:
                    xray.operations.connect_node(node_id)
        except Exception as exc:
            logger.warning("Tunnel apply failed for endpoint %s: %s", node_id, exc)


def run_post_provision(
    node_id: int,
    creds: provisioning.SSHCredentials,
    extras: ProvisionExtras,
) -> None:
    """Configure services, TLS, optional LE, and tunnel after agent registration."""
    with GetDB() as db:
        dbnode = crud.get_node_by_id(db, node_id)
        if not dbnode:
            return

        from app.services.materialize import provision_slug_list
        from app.services.node_apply import set_node_services

        is_wg_core = dbnode.core_kind == CoreKind.wireguard.value
        slugs = provision_slug_list(
            core_kind=dbnode.core_kind,
            enable_hysteria2=extras.enable_hysteria2,
            enable_tuic=extras.enable_tuic,
            enable_anytls=extras.enable_anytls,
            enable_plain_wg=is_wg_core or extras.enable_plain_wg_on_xray,
            enable_awg=extras.enable_awg_on_xray or extras.enable_awg_wg,
            enable_xray=dbnode.core_kind == CoreKind.xray.value,
        )
        if slugs:
            set_node_services(db, dbnode, slugs, replace=False)
            db.refresh(dbnode)

        wants_singbox = extras.enable_hysteria2 or extras.enable_tuic or extras.enable_anytls
        if wants_singbox and dbnode.singbox is None:
            sni = (extras.le_target or dbnode.address).strip()
            crud.provision_singbox_defaults(
                db,
                dbnode,
                hysteria2=extras.enable_hysteria2,
                tuic=extras.enable_tuic,
                sni=sni,
            )
            db.refresh(dbnode)
            if extras.enable_anytls:
                crud.upsert_node_singbox(db, dbnode, anytls_enabled=True, anytls_port=44335)

        if is_wg_core and dbnode.wireguard is None:
            crud.provision_wireguard_defaults(
                db,
                dbnode,
                plain_enabled=True,
                awg_enabled=getattr(extras, "enable_awg_wg", False),
            )
            db.refresh(dbnode)

        cfg = dbnode.singbox
        cert_path = (cfg.certificate_path if cfg else None) or DEFAULT_CERT
        key_path = (cfg.key_path if cfg else None) or DEFAULT_KEY
        sni = (cfg.sni if cfg else None) or dbnode.address

        le_done = False
        if wants_singbox and extras.tls_mode == "letsencrypt" and extras.le_target and extras.le_email:
            try:
                identifier, kind = normalize_tls_target(extras.le_target, extras.le_kind)
                issue_certificate(
                    creds,
                    identifier,
                    extras.le_email,
                    tls_kind=kind,
                    cert_path=cert_path,
                    key_path=key_path,
                )
                crud.upsert_node_singbox(
                    db,
                    dbnode,
                    sni=identifier,
                    tls_le_domain=identifier,
                    tls_le_kind=kind,
                    certificate_path=cert_path,
                    key_path=key_path,
                )
                le_done = True
                db.refresh(dbnode)
            except Exception as exc:
                logger.warning("Post-provision LE failed for node %s: %s", node_id, exc)

        if wants_singbox and extras.tls_mode == "self_signed" and not le_done:
            try:
                install_self_signed(creds, sni, cert_path=cert_path, key_path=key_path)
                crud.upsert_node_singbox(
                    db,
                    dbnode,
                    sni=sni,
                    certificate_path=cert_path,
                    key_path=key_path,
                )
                db.refresh(dbnode)
            except Exception as exc:
                logger.warning("Post-provision self-signed TLS failed for node %s: %s", node_id, exc)

        _maybe_create_tunnel(db, dbnode, extras)

    if wants_singbox:
        _sync_singbox(node_id)

    try:
        from app import xray

        xray.operations.connect_node(node_id)
    except Exception as exc:
        logger.warning("Post-provision connect failed for node %s: %s", node_id, exc)
