"""Materialize catalog + bindings into legacy per-node engine config rows."""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from app.services.catalog import SINGBOX_SLUGS, WIREGUARD_SLUGS, merge_overrides, service_port
from app.tls.acme import DEFAULT_CERT, DEFAULT_KEY

logger = logging.getLogger("shahkar-services-materialize")


def _binding_map(bindings) -> Dict[str, object]:
    return {b.service_slug: b for b in bindings if b.enabled}


def materialize_singbox(db, dbnode, bindings) -> None:
    from app.db import crud

    by_slug = _binding_map(bindings)
    wants = any(s in by_slug for s in SINGBOX_SLUGS)
    if not wants:
        if dbnode.singbox:
            crud.upsert_node_singbox(
                db,
                dbnode,
                hysteria2_enabled=False,
                tuic_enabled=False,
                anytls_enabled=False,
            )
        return

    hy2 = by_slug.get("hysteria2")
    tuic = by_slug.get("tuic")
    anytls = by_slug.get("anytls")
    sni = (dbnode.address or "").strip()

    cfg_hy2 = (hy2.service.config if hy2 and hy2.service else {}) or {}
    cfg_tuic = (tuic.service.config if tuic and tuic.service else {}) or {}
    cfg_at = (anytls.service.config if anytls and anytls.service else {}) or {}

    hy2_m = merge_overrides(cfg_hy2, hy2.overrides if hy2 else None)
    tuic_m = merge_overrides(cfg_tuic, tuic.overrides if tuic else None)
    at_m = merge_overrides(cfg_at, anytls.overrides if anytls else None)

    existing = dbnode.singbox
    cert = (existing.certificate_path if existing else None) or DEFAULT_CERT
    key = (existing.key_path if existing else None) or DEFAULT_KEY
    sni_val = (existing.sni if existing and existing.sni else None) or sni

    crud.upsert_node_singbox(
        db,
        dbnode,
        certificate_path=cert,
        key_path=key,
        sni=sni_val,
        hysteria2_enabled=hy2 is not None,
        hysteria2_port=service_port(hy2_m, None) if hy2 else None,
        hysteria2_up_mbps=hy2_m.get("up_mbps"),
        hysteria2_down_mbps=hy2_m.get("down_mbps"),
        hysteria2_obfs_password=hy2_m.get("obfs_password"),
        tuic_enabled=tuic is not None,
        tuic_port=service_port(tuic_m, None) if tuic else None,
        tuic_congestion_control=tuic_m.get("congestion_control") or "bbr",
        anytls_enabled=anytls is not None,
        anytls_port=service_port(at_m, None) if anytls else None,
    )


def materialize_wireguard(db, dbnode, bindings) -> None:
    from app.db import crud

    by_slug = _binding_map(bindings)
    plain = by_slug.get("wireguard-plain")
    awg = by_slug.get("amneziawg")

    if not plain and not awg:
        return

    if dbnode.wireguard is None:
        crud.provision_wireguard_defaults(
            db,
            dbnode,
            plain_enabled=plain is not None,
            awg_enabled=awg is not None,
        )
        db.refresh(dbnode)
        return

    crud.set_node_wg_stack(
        db,
        dbnode,
        plain_enabled=plain is not None if plain or awg else None,
        awg_enabled=awg is not None if plain or awg else None,
    )

    cfg = dbnode.wireguard
    if plain and plain.service:
        merged = merge_overrides(plain.service.config or {}, plain.overrides)
        if merged.get("listen_port"):
            cfg.listen_port = int(merged["listen_port"])
            # Do not clobber an operator-set client host on every materialize.
            if not (cfg.endpoint or "").strip():
                cfg.endpoint = f"{dbnode.address}:{cfg.listen_port}"
        if merged.get("subnet"):
            cfg.subnet = merged["subnet"]
    if awg and awg.service:
        merged = merge_overrides(awg.service.config or {}, awg.overrides)
        if merged.get("awg_listen_port"):
            cfg.awg_listen_port = int(merged["awg_listen_port"])
            if not (cfg.awg_endpoint or "").strip():
                cfg.awg_endpoint = f"{dbnode.address}:{cfg.awg_listen_port}"
        if merged.get("awg_subnet"):
            cfg.awg_subnet = merged["awg_subnet"]
    db.commit()
    db.refresh(dbnode)


def reconcile_wireguard_endpoints(db, dbnode) -> bool:
    """Keep WG peer endpoints' *ports* aligned; never stomp a custom host.

    Operators set client dial hosts via the WireGuard page / Hosts UI.
    Reconcile may refresh the port (tunnel remap) but must not rewrite a
    custom hostname/IP back to ``nodes.address``.
    """
    from app.subscription.wireguard import (
        _endpoint_host,
        _is_non_routable_host,
        _join_host_port,
        public_dial_host,
    )
    from app.tunnel.relay import relay_wireguard_tunnel_port

    cfg = dbnode.wireguard
    fallback = public_dial_host(dbnode)
    if cfg is None:
        return False
    changed = False
    listen_port = int(cfg.listen_port or 0)
    tun_port = relay_wireguard_tunnel_port(db, int(dbnode.id))
    plain_port = int(tun_port) if tun_port else listen_port

    def _pick_host(current_endpoint: str | None) -> str:
        cur = _endpoint_host(current_endpoint)
        if cur and not _is_non_routable_host(cur):
            return cur
        return fallback

    if plain_port:
        host = _pick_host(cfg.endpoint)
        if host and not _is_non_routable_host(host):
            endpoint = _join_host_port(host, plain_port)
            if cfg.endpoint != endpoint:
                cfg.endpoint = endpoint
                changed = True
    if cfg.awg_listen_port:
        host = _pick_host(cfg.awg_endpoint) or _pick_host(cfg.endpoint)
        if host and not _is_non_routable_host(host):
            awg_endpoint = _join_host_port(host, int(cfg.awg_listen_port))
            if cfg.awg_endpoint != awg_endpoint:
                cfg.awg_endpoint = awg_endpoint
                changed = True
    if changed:
        db.commit()
        db.refresh(cfg)
    return changed


def reconcile_singbox_sni(db, dbnode, *, old_address: str | None = None) -> bool:
    """Keep sing-box TLS SNI aligned when the node's public address changes."""
    cfg = dbnode.singbox
    addr = (dbnode.address or "").strip()
    if cfg is None or not addr:
        return False
    sni = (cfg.sni or "").strip()
    old = (old_address or "").strip()
    if not sni or (old and sni == old):
        if cfg.sni != addr:
            cfg.sni = addr
            db.commit()
            db.refresh(cfg)
            return True
    return False


def materialize_node_services(db, dbnode) -> None:
    """Sync ``node_singbox`` / ``node_wireguard`` from enabled bindings."""
    from app.db import crud

    bindings = crud.get_node_service_bindings(db, dbnode.id, enabled_only=True)
    if not bindings:
        return
    materialize_singbox(db, dbnode, bindings)
    materialize_wireguard(db, dbnode, bindings)
    db.refresh(dbnode)


def provision_slug_list(
    *,
    core_kind: str,
    enable_hysteria2: bool = False,
    enable_tuic: bool = False,
    enable_anytls: bool = False,
    enable_plain_wg: bool = False,
    enable_awg: bool = False,
    enable_xray: bool = True,
) -> List[str]:
    """Map provision checkboxes → catalog slugs."""
    slugs: List[str] = []
    if enable_xray and core_kind == "xray":
        slugs.append("xray")
    if enable_plain_wg or core_kind == "wireguard":
        slugs.append("wireguard-plain")
    if enable_awg:
        slugs.append("amneziawg")
    if enable_hysteria2:
        slugs.append("hysteria2")
    if enable_tuic:
        slugs.append("tuic")
    if enable_anytls:
        slugs.append("anytls")
    return slugs
