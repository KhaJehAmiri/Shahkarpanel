"""CDN / external-proxy support (3x-ui style).

Hosts override what clients see in subscription links (domain:443 + TLS) while
Xray may listen on a different port/security on the origin.

* ``XRAY_CDN_RUNTIME_ENABLED`` — runtime-only loopback + plain transport for
  grpc/ws/xhttp CDN hosts so an origin bridge (nginx or manual) can terminate TLS.
* ``XRAY_CDN_ORIGIN_NGINX`` — auto-generate **proxy-domain-only** nginx vhosts
  (``nexuspanel-cdn-*``). Panel HTTPS (``setup_https.sh``) is never touched.

Reality/tcp/shadowsocks CDN hosts keep Xray bound publicly; subscription still
exports the host address/port with correct TLS/Reality params.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.subscription.tls_client import is_ip_literal
from app.xray.inbound_ports import inbound_port, is_product_inbound

logger = logging.getLogger("nexus-cdn")

EDGE_DIR = Path(os.environ.get("NEXUSPANEL_EDGE_DIR", "/var/lib/nexuspanel/edge"))
DESIRED_JSON = EDGE_DIR / "desired.json"
NGINX_STAGING = EDGE_DIR / "nginx" / "sites"
WEBROOT = Path(os.environ.get("NEXUSPANEL_ACME_WEBROOT", "/var/www/letsencrypt"))
RECONCILE_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "reconcile_edge_nginx.sh"

CDN_NGINX_NETWORKS = frozenset({"grpc", "ws", "httpupgrade", "splithttp", "xhttp"})
# Backward-compatible alias
EDGE_NGINX_NETWORKS = CDN_NGINX_NETWORKS
_DOMAIN_SAFE = re.compile(r"[^a-zA-Z0-9.-]+")


def cdn_runtime_enabled() -> bool:
    from config import XRAY_CDN_RUNTIME_ENABLED

    return bool(XRAY_CDN_RUNTIME_ENABLED)


def cdn_origin_nginx_enabled() -> bool:
    from config import XRAY_CDN_ORIGIN_NGINX

    return bool(XRAY_CDN_ORIGIN_NGINX)


def edge_proxy_enabled() -> bool:
    """Deprecated alias for :func:`cdn_origin_nginx_enabled`."""
    return cdn_origin_nginx_enabled()


@dataclass
class EdgeRoute:
    inbound_tag: str
    domain: str
    public_port: int
    backend_port: int
    network: str
    service_name: str = ""
    ws_path: str = ""
    cert_domain: str = ""
    backend_tls: bool = False

    def site_basename(self) -> str:
        safe = _DOMAIN_SAFE.sub("-", self.domain).strip("-") or "cdn"
        return f"nexuspanel-cdn-{safe}-{self.public_port}"


@dataclass
class EdgeSyncResult:
    routes: list[EdgeRoute] = field(default_factory=list)
    nginx_applied: bool = False
    nginx_message: str = ""
    warnings: list[str] = field(default_factory=list)


def _inbound_listen(ib: dict[str, Any]) -> str:
    listen = str(ib.get("listen") or "0.0.0.0").strip()
    return listen or "0.0.0.0"


def _is_loopback_listen(ib: dict[str, Any]) -> bool:
    listen = _inbound_listen(ib).lower()
    return listen in ("127.0.0.1", "localhost", "::1")


def _inbound_network(ib: dict[str, Any]) -> str:
    stream = ib.get("streamSettings") or {}
    if not isinstance(stream, dict):
        return "tcp"
    return str(stream.get("network") or "tcp").strip().lower()


def _static_domain(address: str) -> str | None:
    addr = str(address or "").strip()
    if not addr or "{" in addr or "}" in addr:
        return None
    host = addr.split(",", 1)[0].strip().split(":", 1)[0].strip()
    if not host or is_ip_literal(host):
        return None
    return host.lower()


def _grpc_service_name(ib: dict[str, Any]) -> str:
    stream = ib.get("streamSettings") or {}
    if not isinstance(stream, dict):
        return ""
    gs = stream.get("grpcSettings") or {}
    if isinstance(gs, dict):
        return str(gs.get("serviceName") or "").strip()
    return ""


def _ws_path(ib: dict[str, Any]) -> str:
    stream = ib.get("streamSettings") or {}
    if not isinstance(stream, dict):
        return "/"
    ws = stream.get("wsSettings") or {}
    if isinstance(ws, dict):
        path = str(ws.get("path") or "").strip()
        if path:
            return path if path.startswith("/") else f"/{path}"
    return "/"


def _transport_path(ib: dict[str, Any], network: str) -> str:
    stream = ib.get("streamSettings") or {}
    if not isinstance(stream, dict):
        return "/"
    key = {
        "ws": "wsSettings",
        "httpupgrade": "httpupgradeSettings",
        "splithttp": "splithttpSettings",
        "xhttp": "xhttpSettings",
    }.get(network, "wsSettings")
    block = stream.get(key) or {}
    if isinstance(block, dict):
        path = str(block.get("path") or "").strip()
        if path:
            return path if path.startswith("/") else f"/{path}"
    return _ws_path(ib)


def _host_public_port(host: dict[str, Any], inbound: dict[str, Any]) -> int | None:
    raw = host.get("port")
    if raw is not None:
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    return inbound_port(inbound)


def is_cdn_fronted_host(host: dict[str, Any], inbound: dict[str, Any]) -> bool:
    """True when clients reach a domain:port that differs from the Xray bind port."""
    if host.get("is_disabled"):
        return False
    domain = _static_domain(str(host.get("address") or ""))
    if not domain:
        return False
    in_port = inbound_port(inbound)
    pub_port = _host_public_port(host, inbound)
    if in_port is None or pub_port is None:
        return False
    return int(pub_port) != int(in_port)


def _inbound_security(ib: dict[str, Any]) -> str:
    stream = ib.get("streamSettings") or {}
    if not isinstance(stream, dict):
        return "none"
    return str(stream.get("security") or "none").strip().lower()


def _nginx_bridgeable_inbound(inbound: dict[str, Any]) -> bool:
    """Nginx origin can only bridge HTTP-shaped transports without Reality."""
    if _inbound_security(inbound) == "reality":
        return False
    return _inbound_network(inbound) in CDN_NGINX_NETWORKS


def cdn_runtime_inbound_tags(
    hosts_by_tag: dict[str, list[Any]],
    inbounds: list[dict[str, Any]],
) -> set[str]:
    """Inbounds that need loopback runtime override for nginx-bridgeable CDN hosts."""
    inbound_by_tag = {
        str(ib.get("tag")): ib
        for ib in (inbounds or [])
        if isinstance(ib, dict) and ib.get("tag")
    }
    tags: set[str] = set()
    for tag, hosts in (hosts_by_tag or {}).items():
        inbound = inbound_by_tag.get(tag)
        if not inbound or not is_product_inbound(inbound):
            continue
        if not _nginx_bridgeable_inbound(inbound):
            continue
        for host in hosts or []:
            if is_cdn_fronted_host(_host_as_dict(host), inbound):
                tags.add(tag)
                break
    return tags


def compute_edge_routes(
    hosts_by_tag: dict[str, list[Any]],
    inbounds: list[dict[str, Any]],
) -> list[EdgeRoute]:
    """Build CDN origin nginx routes from DB hosts + inbounds."""
    inbound_by_tag = {
        str(ib.get("tag")): ib
        for ib in (inbounds or [])
        if isinstance(ib, dict) and ib.get("tag")
    }
    routes: list[EdgeRoute] = []
    seen: set[tuple[str, str, int]] = set()

    for tag, hosts in (hosts_by_tag or {}).items():
        inbound = inbound_by_tag.get(tag)
        if not inbound or not is_product_inbound(inbound):
            continue
        if not _nginx_bridgeable_inbound(inbound):
            continue

        for host in hosts or []:
            h = _host_as_dict(host)
            if not is_cdn_fronted_host(h, inbound):
                continue

            domain = _static_domain(str(h.get("address") or ""))
            pub_port = _host_public_port(h, inbound)
            in_port = inbound_port(inbound)
            if not domain or pub_port is None or in_port is None:
                continue

            key = (tag, domain, int(pub_port))
            if key in seen:
                continue
            seen.add(key)

            network = _inbound_network(inbound)
            ws_path = str(h.get("path") or "").strip() or _transport_path(inbound, network)
            if ws_path and not ws_path.startswith("/"):
                ws_path = f"/{ws_path}"

            routes.append(
                EdgeRoute(
                    inbound_tag=tag,
                    domain=domain,
                    public_port=int(pub_port),
                    backend_port=int(in_port),
                    network=_inbound_network(inbound),
                    service_name=_grpc_service_name(inbound),
                    ws_path=ws_path,
                    cert_domain=domain,
                )
            )

    return routes


def _has_direct_domain_hosts(hosts: list[Any], inbound: dict[str, Any]) -> bool:
    """True when any enabled host reaches the inbound port directly (not CDN :443)."""
    for host in hosts or []:
        h = _host_as_dict(host)
        if h.get("is_disabled"):
            continue
        if not _static_domain(str(h.get("address") or "")):
            continue
        if not is_cdn_fronted_host(h, inbound):
            return True
    return False


def cdn_inbound_tags(routes: list[EdgeRoute]) -> set[str]:
    return {r.inbound_tag for r in routes}


def apply_edge_runtime_to_config(config) -> Any:
    """Runtime-only Xray overrides for CDN nginx-bridge inbounds (stored JSON unchanged)."""
    if not cdn_runtime_enabled():
        return config

    from app.db import GetDB

    runtime = config.copy() if hasattr(config, "copy") else deepcopy(config)
    inbounds = list(runtime.get("inbounds") or [])

    with GetDB() as db:
        if hasattr(runtime, "inbounds_by_tag"):
            tags = list(runtime.inbounds_by_tag.keys())
        else:
            tags = [str(ib.get("tag")) for ib in inbounds if ib.get("tag")]
        hosts_by_tag = _materialize_hosts_by_tag(db, tags)

    runtime_tags = cdn_runtime_inbound_tags(hosts_by_tag, inbounds)
    if not runtime_tags:
        return runtime

    routes = compute_edge_routes(hosts_by_tag, inbounds)
    direct_tags: set[str] = set()
    for tag in runtime_tags:
        inbound = next((ib for ib in inbounds if str(ib.get("tag") or "") == tag), None)
        if inbound and _has_direct_domain_hosts(hosts_by_tag.get(tag) or [], inbound):
            direct_tags.add(tag)
            for route in routes:
                if route.inbound_tag == tag:
                    route.backend_tls = True

    for ib in inbounds:
        if not isinstance(ib, dict):
            continue
        tag = str(ib.get("tag") or "")
        if tag not in runtime_tags:
            continue
        if tag in direct_tags:
            continue
        if _is_loopback_listen(ib) and str((ib.get("streamSettings") or {}).get("security") or "").lower() == "none":
            continue
        ib["listen"] = "127.0.0.1"
        stream = ib.setdefault("streamSettings", {})
        if not isinstance(stream, dict):
            continue
        stream["security"] = "none"
        stream.pop("tlsSettings", None)
        stream.pop("realitySettings", None)

    runtime["inbounds"] = inbounds
    return runtime


def _nginx_grpc_location(route: EdgeRoute) -> str:
    svc = route.service_name or "grpc"
    pattern = re.escape(svc)
    scheme = "grpcs" if route.backend_tls else "grpc"
    return f"""    location ~ ^/{pattern} {{
        grpc_pass {scheme}://127.0.0.1:{route.backend_port};
        grpc_set_header Host $host;
        grpc_set_header X-Real-IP $remote_addr;
        grpc_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        grpc_read_timeout 1h;
        grpc_send_timeout 1h;
    }}"""


def _nginx_ws_location(route: EdgeRoute) -> str:
    path = route.ws_path or "/"
    loc = path.rstrip("/") or "/"
    if route.backend_tls:
        return f"""    location {loc} {{
        proxy_pass https://127.0.0.1:{route.backend_port};
        proxy_ssl_server_name on;
        proxy_ssl_verify off;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 1h;
        proxy_send_timeout 1h;
    }}"""
    return f"""    location {loc} {{
        proxy_pass http://127.0.0.1:{route.backend_port};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 1h;
        proxy_send_timeout 1h;
    }}"""


def _nginx_proxy_block(route: EdgeRoute) -> str:
    if route.network == "grpc":
        return _nginx_grpc_location(route)
    return _nginx_ws_location(route)


def _origin_tls_listen_port(public_port: int) -> int:
    """Port nginx listens on for CDN origin TLS.

    ``public_port`` is what clients use at the edge (often Cloudflare :80/:443).
    The origin vhost must terminate TLS on 443 — never ``listen 80 ssl``.
    """
    if int(public_port) == 80:
        return 443
    return int(public_port)


def _edge_cert_paths(domain: str) -> tuple[str, str] | None:
    """Return Let's Encrypt cert paths for a CDN origin domain when they exist."""
    d = (domain or "").strip()
    if not d or d == "_":
        return None
    cert = Path(f"/etc/letsencrypt/live/{d}/fullchain.pem")
    key = Path(f"/etc/letsencrypt/live/{d}/privkey.pem")
    if cert.is_file() and key.is_file():
        return str(cert), str(key)
    return None


def render_nginx_site(routes: list[EdgeRoute]) -> str:
    if not routes:
        return ""
    primary = routes[0]
    tags = ", ".join(sorted({r.inbound_tag for r in routes}))

    # Only emit the TLS server block once the certificate actually exists on
    # disk. Emitting `ssl_certificate` for a missing cert makes `nginx -t` fail
    # for the WHOLE server — one CDN origin domain whose cert can't be issued
    # yet (e.g. its DNS still points at the CDN edge, so HTTP-01 on this origin
    # never resolves here) would otherwise wedge every reload and take down the
    # panel's own vhost and all subscription vhosts with it. Ship an HTTP-only
    # placeholder (ACME challenge + 503) until the cert lands; a later sync pass
    # re-renders with TLS. Mirrors the subscription renderer's cert fallback.
    tls = _edge_cert_paths(primary.cert_domain)
    if not tls:
        return f"""# CDN origin (cert pending for {primary.cert_domain}) — managed by NexusPanel
server {{
    listen 80;
    listen [::]:80;
    server_name {primary.domain};
    location /.well-known/acme-challenge/ {{
        root {WEBROOT};
        default_type "text/plain";
    }}
    location / {{ return 503; }}
}}
"""

    cert, key = tls
    origin_port = _origin_tls_listen_port(primary.public_port)
    listen_public = (
        f"    listen {origin_port} ssl http2;\n"
        f"    listen [::]:{origin_port} ssl http2;"
    )
    proxy_blocks = "\n\n".join(_nginx_proxy_block(route) for route in routes)

    return f"""# CDN origin TLS → Xray ({tags}) — managed by NexusPanel (not the panel web vhost)
server {{
    listen 80;
    listen [::]:80;
    server_name {primary.domain};
    location /.well-known/acme-challenge/ {{
        root {WEBROOT};
        default_type "text/plain";
    }}
    location / {{ return 301 https://$host$request_uri; }}
}}

server {{
{listen_public}
    server_name {primary.domain};

    ssl_certificate     {cert};
    ssl_certificate_key {key};
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 1d;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

{proxy_blocks}

    location / {{ return 444; }}
}}
"""


def build_desired_state(routes: list[EdgeRoute]) -> dict[str, Any]:
    from collections import defaultdict

    grouped: dict[tuple[str, int], list[EdgeRoute]] = defaultdict(list)
    for route in routes:
        grouped[(route.domain, route.public_port)].append(route)

    sites: dict[str, str] = {}
    merged_routes: list[EdgeRoute] = []
    for (domain, public_port), group in grouped.items():
        safe = _DOMAIN_SAFE.sub("-", domain).strip("-") or "cdn"
        basename = f"nexuspanel-cdn-{safe}-{public_port}"
        sites[basename] = render_nginx_site(group)
        merged_routes.extend(group)
    return {
        "version": 2,
        "routes": [asdict(r) for r in merged_routes],
        "sites": sites,
        "webroot": str(WEBROOT),
    }


def write_desired_state(routes: list[EdgeRoute]) -> Path | None:
    try:
        EDGE_DIR.mkdir(parents=True, exist_ok=True)
        NGINX_STAGING.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("cdn dir not writable: %s", exc)
        return None
    state = build_desired_state(routes)
    try:
        DESIRED_JSON.write_text(json.dumps(state, indent=2), encoding="utf-8")
        for name, content in state["sites"].items():
            (NGINX_STAGING / f"{name}.conf").write_text(content, encoding="utf-8")
        stale = {p.name for p in NGINX_STAGING.glob("*.conf")}
        wanted = {f"{n}.conf" for n in state["sites"]}
        for name in stale - wanted:
            (NGINX_STAGING / name).unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("cdn state write failed: %s", exc)
        return None
    return DESIRED_JSON


def _nginx_reconcile_env() -> dict[str, str]:
    env = os.environ.copy()
    for candidate in (
        os.environ.get("NGINX_BIN", ""),
        "/usr/sbin/nginx",
        "/usr/bin/nginx",
    ):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            env["PATH"] = f"{os.path.dirname(candidate)}:{env.get('PATH', '')}"
            break
    return env


def _reconcile_script_succeeded(proc: subprocess.CompletedProcess[str]) -> tuple[bool, str]:
    out = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode == 0:
        return True, out or "nginx reconciled"
    if "Installed" in out or "nginx reloaded" in out:
        return True, out
    return False, out or f"reconcile failed (exit {proc.returncode})"


def _run_reconcile_script(script: Path) -> tuple[bool, str]:
    if not script.is_file():
        return False, f"Reconcile script missing: {script}"
    try:
        proc = subprocess.run(
            [str(script), "--apply"],
            capture_output=True,
            text=True,
            timeout=120,
            env=_nginx_reconcile_env(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    return _reconcile_script_succeeded(proc)


def _privileged_reconcile_script(script: Path) -> tuple[bool, str]:
    """Re-run reconcile as root inside this container (panel runs as ``nexuspanel``)."""
    from app.xray.core import XRayCore

    cid = XRayCore._self_container_id()
    if not cid:
        return False, "nginx reconcile requires root (docker.sock unavailable for escalation)"
    try:
        proc = subprocess.run(
            ["docker", "exec", "--user", "root", cid, str(script), "--apply"],
            capture_output=True,
            text=True,
            timeout=120,
            env=_nginx_reconcile_env(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    return _reconcile_script_succeeded(proc)


def _try_reconcile_with_privilege(script: Path) -> tuple[bool, str]:
    applied, message = _run_reconcile_script(script)
    if applied:
        return True, message
    if "run as root" in message.lower():
        logger.info("escalating nginx reconcile via docker exec --user root")
        return _privileged_reconcile_script(script)
    return False, message


def try_reconcile_nginx() -> tuple[bool, str]:
    return _try_reconcile_with_privilege(RECONCILE_SCRIPT)


def _host_as_dict(host: Any) -> dict[str, Any]:
    if isinstance(host, dict):
        return host
    if hasattr(host, "model_dump") and not hasattr(host, "__table__"):
        return host.model_dump()
    try:
        from app.models.proxy import ProxyHost as ProxyHostModel

        return ProxyHostModel.model_validate(host, from_attributes=True).model_dump()
    except Exception:
        pass
    fields = (
        "remark", "address", "port", "sni", "host", "path",
        "allowinsecure", "is_disabled", "mux_enable", "fragment_setting",
        "noise_setting", "random_user_agent", "use_sni_as_host",
    )
    out: dict[str, Any] = {}
    # SQLAlchemy ORM rows: never use ``hasattr(host, key)`` — it can lazy-load
    # expired attributes on a detached instance and raise DetachedInstanceError.
    if hasattr(host, "__table__"):
        from sqlalchemy import inspect as sa_inspect

        loaded = sa_inspect(host).dict
        row = getattr(host, "__dict__", {})
        for key in fields:
            if key not in loaded and key not in row:
                continue
            val = loaded.get(key, row.get(key))
            if hasattr(val, "value"):
                val = val.value
            out[key] = val
        return out
    for key in fields:
        if hasattr(host, key):
            val = getattr(host, key)
            if hasattr(val, "value"):
                val = val.value
            out[key] = val
    return out


def _materialize_hosts_by_tag(db, tags: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Load proxy hosts as plain dicts while the SQLAlchemy session is still open."""
    from app.db import crud

    return {
        tag: [_host_as_dict(h) for h in crud.get_hosts(db, tag)]
        for tag in tags
    }


def clear_edge_nginx() -> EdgeSyncResult:
    """Remove all CDN origin nginx vhosts and write an empty desired state."""
    result = EdgeSyncResult()
    write_desired_state([])
    applied, message = try_reconcile_nginx()
    result.nginx_applied = applied
    result.nginx_message = message or "cdn origin nginx configs cleared"
    return result


def sync_edge_nginx(db) -> EdgeSyncResult:
    """Compute CDN routes, write origin nginx state, and reconcile nginx."""
    from app import xray

    result = EdgeSyncResult()
    hosts_by_tag = _materialize_hosts_by_tag(db, list(xray.config.inbounds_by_tag))
    inbounds = list(xray.config.get("inbounds") or [])

    for tag, hosts in hosts_by_tag.items():
        inbound = xray.config.get_inbound(tag)
        if not inbound:
            continue
        network = _inbound_network(inbound)
        for host in hosts:
            h = _host_as_dict(host)
            if not h.get("is_disabled") and is_cdn_fronted_host(h, inbound):
                network = _inbound_network(inbound)
                sec = _inbound_security(inbound)
                if sec == "reality" or network not in CDN_NGINX_NETWORKS:
                    result.warnings.append(
                        f'Inbound "{tag}" CDN host uses {network}/{sec} — '
                        "use direct IP/grey-cloud DNS or bind Xray on a Cloudflare "
                        "origin port (443/2053/8443); nginx origin bridge is grpc/ws only."
                    )

    if not cdn_origin_nginx_enabled():
        cleared = clear_edge_nginx()
        cleared.warnings.extend(result.warnings)
        cleared.warnings.append(
            "CDN origin nginx is disabled — configure origin bridge manually or "
            "set XRAY_CDN_ORIGIN_NGINX=True."
        )
        return cleared

    result.routes = compute_edge_routes(hosts_by_tag, inbounds)
    for route in result.routes:
        inbound = xray.config.get_inbound(route.inbound_tag)
        if inbound and _has_direct_domain_hosts(hosts_by_tag.get(route.inbound_tag) or [], inbound):
            route.backend_tls = True

    write_desired_state(result.routes)
    applied, message = try_reconcile_nginx()

    # The first reconcile pass renders cert-pending domains HTTP-only (see
    # render_nginx_site) and issues their certs. Re-render + reconcile so any
    # domain whose cert just landed gets its real TLS vhost, exactly like the
    # subscription sync's two-pass. Without this, a freshly-issued cert would
    # sit unused until the next unrelated sync.
    if result.routes:
        write_desired_state(result.routes)
        applied2, message2 = try_reconcile_nginx()
        if applied2:
            applied = True
        if message2:
            message = f"{message}\n{message2}" if message else message2

    result.nginx_applied = applied
    result.nginx_message = message
    if result.routes and not applied:
        result.warnings.append(
            "cdn origin nginx pending — run on host: sudo scripts/reconcile_edge_nginx.sh --apply"
        )
    return result


SUB_LEGACY_DIR = EDGE_DIR / "subscription"
SUB_LEGACY_STAGING = SUB_LEGACY_DIR / "nginx" / "sites"
SUB_LEGACY_JSON = SUB_LEGACY_DIR / "desired.json"
SUB_LEGACY_BACKEND = os.environ.get(
    "NEXUSPANEL_SUB_BACKEND", "http://127.0.0.1:8000"
)
SUB_LEGACY_RECONCILE_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "reconcile_subscription_nginx.sh"


def _subscription_tls_cert_paths(host: str) -> tuple[str, str] | None:
    """Return Let's Encrypt cert paths when a cert exists for ``host``."""
    domain = (host or "").strip()
    if not domain or domain == "_":
        return None
    cert = Path(f"/etc/letsencrypt/live/{domain}/fullchain.pem")
    key = Path(f"/etc/letsencrypt/live/{domain}/privkey.pem")
    if cert.is_file() and key.is_file():
        return str(cert), str(key)
    return None


def _render_subscription_acme_site(host: str) -> str:
    """Port 80 vhost for ACME HTTP-01 and HTTP→HTTPS redirect."""
    return f"""# Subscription domain ACME — managed by NexusPanel
server {{
    listen 80;
    listen [::]:80;
    server_name {host};

    location /.well-known/acme-challenge/ {{
        root {WEBROOT};
        default_type "text/plain";
    }}

    location / {{
        return 301 https://$host$request_uri;
    }}
}}
"""


def _render_subscription_panel_https_site(host: str) -> str:
    """Port 443 TLS vhost — full panel proxy for subscription domains with certs."""
    tls = _subscription_tls_cert_paths(host)
    if not tls:
        return ""
    cert, key = tls
    return f"""# Subscription domain HTTPS (443) — managed by NexusPanel
server {{
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name {host};

    ssl_certificate     {cert};
    ssl_certificate_key {key};
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 1d;

    client_max_body_size 200m;

    location / {{
        proxy_pass {SUB_LEGACY_BACKEND};
        proxy_http_version 1.1;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }}
}}
"""


def _render_subscription_legacy_site(
    host: str,
    listen_port: int,
    path_prefixes: list[str],
    *,
    force_tls: bool = False,
    fallback_tls: tuple[str, str] | None = None,
) -> str:
    """One nginx server block per (host, port) with all path prefixes as locations."""
    server_name = host or "_"
    unique_prefixes = sorted({(p or "sub").strip("/") for p in path_prefixes if (p or "").strip()})
    if not unique_prefixes:
        unique_prefixes = ["sub"]
    locations = ""
    for prefix in unique_prefixes:
        loc = f"/{prefix}/"
        locations += f"""
    location {loc} {{
        proxy_pass {SUB_LEGACY_BACKEND};
        proxy_http_version 1.1;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
"""
    # Browser UI belongs on standard HTTPS (443) — legacy sub port lacks /_next assets.
    if host and host != "_":
        locations += """
    location /subscribe/ {
        return 301 https://$server_name$request_uri;
    }
"""
    else:
        locations += f"""
    location /subscribe/ {{
        proxy_pass {SUB_LEGACY_BACKEND};
        proxy_http_version 1.1;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
"""
    tls = _subscription_tls_cert_paths(host) or (fallback_tls if force_tls else None)
    if tls:
        cert, key = tls
        listen_directive = f"""    listen {listen_port} ssl;
    listen [::]:{listen_port} ssl;
    ssl_certificate     {cert};
    ssl_certificate_key {key};
    ssl_protocols       TLSv1.2 TLSv1.3;"""
    else:
        listen_directive = f"""    listen {listen_port};
    listen [::]:{listen_port};"""
    return f"""# Legacy 3x-ui subscription port — managed by NexusPanel
server {{
{listen_directive}
    server_name {server_name};
{locations}
    location / {{
        return 444;
    }}
}}
"""


def try_reconcile_subscription_nginx() -> tuple[bool, str]:
    return _try_reconcile_with_privilege(SUB_LEGACY_RECONCILE_SCRIPT)


def sync_subscription_legacy_nginx(db) -> dict[str, Any]:
    """Write nginx vhosts for subscription endpoints with non-443 listen ports."""
    from app.db import crud

    result: dict[str, Any] = {"sites": {}, "applied": False, "message": ""}
    endpoints = [
        ep
        for ep in crud.list_subscription_endpoints(db, enabled_only=True)
        if ep.listen_port and int(ep.listen_port) not in (80, 443)
    ]
    grouped: dict[tuple[str, int], list[str]] = {}
    for ep in endpoints:
        port = int(ep.listen_port)
        host = ep.host or "_"
        prefix = (ep.path_prefix or "sub").strip("/")
        grouped.setdefault((host, port), []).append(prefix)

    # nginx shares one socket per listen port — if any vhost on a port uses TLS,
    # every vhost on that port must define ssl_certificate (SNI per server_name).
    port_fallback_tls: dict[int, tuple[str, str]] = {}
    for host, port in grouped:
        tls = _subscription_tls_cert_paths(host)
        if tls and port not in port_fallback_tls:
            port_fallback_tls[port] = tls

    def _build_sites() -> dict[str, str]:
        site_map: dict[str, str] = {}
        for (host, port), prefixes in grouped.items():
            safe = _DOMAIN_SAFE.sub("-", host).strip("-") or "legacy"
            basename = f"nexuspanel-sub-{safe}-{port}"
            force_tls = port in port_fallback_tls
            site_map[basename] = _render_subscription_legacy_site(
                host,
                port,
                prefixes,
                force_tls=force_tls,
                fallback_tls=port_fallback_tls.get(port),
            )
            if host and host != "_":
                acme_name = f"nexuspanel-sub-acme-{safe}"
                site_map[acme_name] = _render_subscription_acme_site(host)
                if _subscription_tls_cert_paths(host):
                    https_name = f"nexuspanel-sub-https-{safe}"
                    site_map[https_name] = _render_subscription_panel_https_site(host)
        return site_map

    domains: set[str] = {host for host, _port in grouped if host and host != "_"}
    sites = _build_sites()

    def _write_staging(site_map: dict[str, str]) -> None:
        SUB_LEGACY_DIR.mkdir(parents=True, exist_ok=True)
        SUB_LEGACY_STAGING.mkdir(parents=True, exist_ok=True)
        SUB_LEGACY_JSON.write_text(
            json.dumps({"domains": sorted(domains), "sites": site_map}, indent=2),
            encoding="utf-8",
        )
        for name, content in site_map.items():
            (SUB_LEGACY_STAGING / f"{name}.conf").write_text(content, encoding="utf-8")
        stale = {p.name for p in SUB_LEGACY_STAGING.glob("*.conf")}
        wanted = {f"{n}.conf" for n in site_map}
        for name in stale - wanted:
            (SUB_LEGACY_STAGING / name).unlink(missing_ok=True)

    try:
        _write_staging(sites)
    except OSError as exc:
        result["message"] = str(exc)
        return result

    if sites:
        applied, message = try_reconcile_subscription_nginx()
        result["applied"] = applied
        result["message"] = message
        # Re-render subscription vhosts now that reconcile may have issued certs.
        port_fallback_tls.clear()
        for host, port in grouped:
            tls = _subscription_tls_cert_paths(host)
            if tls and port not in port_fallback_tls:
                port_fallback_tls[port] = tls
        sites_tls = _build_sites()
        try:
            _write_staging(sites_tls)
            applied2, message2 = try_reconcile_subscription_nginx()
            if applied2:
                result["applied"] = True
            if message2:
                result["message"] = (result.get("message") or "") + "\n" + message2
            result["sites"] = sites_tls
        except OSError as exc:
            result["message"] = (result.get("message") or "") + f"\n{exc}"
            result["sites"] = sites
    else:
        result["sites"] = sites
    return result


def edge_status(db) -> dict[str, Any]:
    from app import xray

    hosts_by_tag = _materialize_hosts_by_tag(db, list(xray.config.inbounds_by_tag))
    inbounds = list(xray.config.get("inbounds") or [])
    routes = compute_edge_routes(hosts_by_tag, inbounds) if cdn_origin_nginx_enabled() else []
    desired_exists = DESIRED_JSON.is_file()
    nginx_writable = Path("/etc/nginx/sites-enabled").exists() and os.access(
        "/etc/nginx/sites-enabled", os.W_OK
    )
    sub_legacy = SUB_LEGACY_JSON.is_file()
    return {
        "cdn_runtime_enabled": cdn_runtime_enabled(),
        "cdn_origin_nginx_enabled": cdn_origin_nginx_enabled(),
        "enabled": cdn_origin_nginx_enabled(),
        "routes": [asdict(r) for r in routes],
        "runtime_tags": sorted(cdn_runtime_inbound_tags(hosts_by_tag, inbounds)),
        "desired_written": desired_exists,
        "subscription_legacy_written": sub_legacy,
        "nginx_writable": nginx_writable,
        "staging_dir": str(NGINX_STAGING),
        "reconcile_script": str(RECONCILE_SCRIPT),
    }

