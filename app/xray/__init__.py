from random import randint
from typing import TYPE_CHECKING, Dict, Sequence

import commentjson
import json
from pathlib import Path

from app.models.proxy import ProxyHostSecurity
from app.utils.store import DictStorage
from app.utils.system import check_port
from app.xray import operations
from app.xray.config import XRayConfig
from app.xray.core import XRayCore
from app.xray.node import XRayNode
from config import XRAY_ASSETS_PATH, XRAY_EXECUTABLE_PATH, XRAY_JSON
from xray_api import XRay as XRayAPI
from xray_api import exceptions, types
from xray_api import exceptions as exc

core = XRayCore(XRAY_EXECUTABLE_PATH, XRAY_ASSETS_PATH)


def _load_xray_config(api_port: int) -> XRayConfig:
    """Load panel Xray JSON from disk, normalizing legacy/partial configs."""
    from app.xray.inbound_normalize import normalize_core_config_payload

    path = Path(XRAY_JSON)
    if path.is_file():
        with open(path, encoding="utf-8") as f:
            raw = commentjson.loads(f.read())
        normalized = normalize_core_config_payload(raw)
        needs_repair = (
            not isinstance(raw.get("inbounds"), list)
            or not isinstance(raw.get("outbounds"), list)
            or not raw.get("outbounds")
            or json.dumps(normalized, sort_keys=True) != json.dumps(raw, sort_keys=True)
        )
        if needs_repair:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(json.dumps(normalized, indent=4))
            except OSError:
                pass
        return XRayConfig(normalized, api_port=api_port)
    return XRayConfig({}, api_port=api_port)


# Search for a free API port
try:
    for api_port in range(randint(10000, 60000), 65536):
        if not check_port(api_port):
            break
finally:
    config = _load_xray_config(api_port)
    del api_port

_config_loaded_mtime: float = (
    Path(XRAY_JSON).stat().st_mtime if Path(XRAY_JSON).is_file() else 0.0
)


def refresh_for_subscription() -> None:
    """Reload Xray JSON (when changed on disk) and hosts from DB for client exports."""
    global config, _config_loaded_mtime
    path = Path(XRAY_JSON)
    mtime = path.stat().st_mtime if path.is_file() else 0.0
    if mtime > _config_loaded_mtime:
        config = _load_xray_config(config.api_port)
        _config_loaded_mtime = mtime
        hosts.clear()
    if not hosts:
        hosts.update()

api = XRayAPI(config.api_host, config.api_port)

nodes: Dict[int, XRayNode] = {}


if TYPE_CHECKING:
    from app.db.models import ProxyHost


@DictStorage
def hosts(storage: dict):
    from app.db import GetDB, crud

    storage.clear()
    with GetDB() as db:
        for inbound_tag in config.inbounds_by_tag:
            inbound_hosts: Sequence[ProxyHost] = crud.get_hosts(db, inbound_tag)

            storage[inbound_tag] = [
                {
                    "remark": host.remark,
                    "address": [i.strip() for i in host.address.split(',')] if host.address else [],
                    "port": host.port,
                    "path": host.path if host.path else None,
                    "sni": [i.strip() for i in host.sni.split(',')] if host.sni else [],
                    "host": [i.strip() for i in host.host.split(',')] if host.host else [],
                    "alpn": host.alpn.value,
                    "fingerprint": host.fingerprint.value,
                    "tls": None
                    if host.security in (ProxyHostSecurity.inbound_default, ProxyHostSecurity.same)
                    else host.security.value,
                    "allowinsecure": host.allowinsecure,
                    "mux_enable": host.mux_enable,
                    "fragment_setting": host.fragment_setting,
                    "noise_setting": host.noise_setting,
                    "random_user_agent": host.random_user_agent,
                    "use_sni_as_host": host.use_sni_as_host,
                    "sort_order": host.sort_order or 0,
                    "override_sni_from_address": host.override_sni_from_address,
                    "keep_sni_blank": host.keep_sni_blank,
                    "pinned_peer_cert_sha256": host.pinned_peer_cert_sha256,
                    "verify_peer_cert_by_name": host.verify_peer_cert_by_name,
                    "ech_config_list": host.ech_config_list,
                    "mux_params": host.mux_params,
                    "sockopt_params": host.sockopt_params,
                    "final_mask": host.final_mask,
                    "vless_route": host.vless_route,
                    "exclude_from_sub_types": host.exclude_from_sub_types,
                    "mihomo_ip_version": host.mihomo_ip_version,
                    "external_proxy": host.external_proxy,
                    "node_ids": host.node_ids,
                    "region": host.region,
                }
                for host in sorted(inbound_hosts, key=lambda h: (h.sort_order or 0, h.id or 0))
                if not host.is_disabled
            ]


__all__ = [
    "config",
    "hosts",
    "core",
    "api",
    "nodes",
    "operations",
    "exceptions",
    "exc",
    "types",
    "XRayConfig",
    "XRayCore",
    "XRayNode",
    "refresh_for_subscription",
]
