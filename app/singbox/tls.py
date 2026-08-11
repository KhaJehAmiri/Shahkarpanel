"""Refresh sing-box TLS metadata from the live node certificate."""
from datetime import datetime
from typing import Any, Dict, Optional

from app.singbox.transport import client_for_node


def fetch_remote_tls_status(node_object, certificate_path: str) -> Dict[str, Any]:
    """Ask a connected node agent to inspect its TLS cert file."""
    if node_object is None:
        return {"present": False, "trusted": False}
    try:
        from app.singbox.transport import _declares

        if _declares(node_object, "make_request"):
            return node_object.make_request(
                "/singbox/tls/status",
                10,
                certificate_path=certificate_path,
            ) or {"present": False, "trusted": False}
        # Declaration lookup: a plain ``hasattr`` would invoke the ``remote``
        # property and dial the node just to test for the attribute.
        if _declares(node_object, "remote"):
            import json

            raw = node_object.remote.singbox_tls_status(certificate_path)
            if isinstance(raw, str):
                return json.loads(raw) if raw else {"present": False, "trusted": False}
            return raw or {"present": False, "trusted": False}
    except Exception:
        return {"present": False, "trusted": False}
    return {"present": False, "trusted": False}


def apply_tls_status_to_config(cfg, status: Dict[str, Any], *, le_domain: Optional[str] = None) -> None:
    """Persist TLS inspection results on a ``NodeSingBox`` row."""
    cfg.tls_trusted = bool(status.get("trusted"))
    cfg.tls_issuer = status.get("issuer")
    expires = status.get("expires_at")
    if expires:
        try:
            cfg.tls_expires_at = datetime.fromisoformat(expires.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            cfg.tls_expires_at = None
    if le_domain:
        cfg.tls_le_domain = le_domain


def refresh_node_tls(db, dbnode) -> Dict[str, Any]:
    """Poll the node for cert metadata and update the DB row."""
    from app import xray
    from app.db import crud

    cfg = dbnode.singbox
    if cfg is None:
        return {"present": False, "trusted": False}
    cert_path = cfg.certificate_path or "/var/lib/shahkar-node/tls/cert.pem"
    node_object = xray.nodes.get(dbnode.id)
    status = fetch_remote_tls_status(node_object, cert_path)
    apply_tls_status_to_config(cfg, status, le_domain=cfg.tls_le_domain or cfg.sni)
    db.commit()
    db.refresh(cfg)
    return status
