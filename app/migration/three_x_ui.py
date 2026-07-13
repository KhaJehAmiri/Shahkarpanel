"""Import inbounds, clients, and subscription settings from 3x-ui panels."""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from sqlalchemy.orm import Session

from app.db import crud
from app.models.subscription_endpoint import SubscriptionExportMode
from app.models.user import UserCreate, UserModify, UserStatus, UserStatusCreate
from app.models.proxy import ProxyHost as ProxyHostModel

logger = logging.getLogger("nexus-migration-3xui")

_TAG_SAFE = re.compile(r"[^a-zA-Z0-9_-]+")
_USERNAME_MAX = 34


def _migration_username(slug: str, email: str, client: dict) -> str:
    """Stable panel username — never collapse distinct clients after truncation."""
    import hashlib

    sub_id = str(client.get("subId") or client.get("sub_id") or "").strip()
    if sub_id:
        raw = _TAG_SAFE.sub("_", f"{slug}_{sub_id}")
    else:
        raw = _TAG_SAFE.sub("_", f"{slug}_{email}")
    raw = raw.strip("_") or "user"
    if len(raw) <= _USERNAME_MAX:
        return raw
    digest = hashlib.sha1(raw.encode()).hexdigest()[:10]
    prefix = _TAG_SAFE.sub("_", slug).strip("_")[: (_USERNAME_MAX - 11)]
    return f"{prefix}_{digest}"[:_USERNAME_MAX]


@dataclass
class PanelSource:
    slug: str
    base_url: str = ""
    username: str = ""
    password: str = ""
    backup_path: str = ""
    legacy_panel_id: str = ""


@dataclass
class MigrationPreview:
    panel_slug: str
    endpoint: dict
    inbound_tags: list[str] = field(default_factory=list)
    user_count: int = 0
    alias_count: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass
class MigrationResult(MigrationPreview):
    applied: bool = False
    users_created: int = 0
    users_updated: int = 0
    aliases_created: int = 0
    hosts_created: int = 0
    validation: dict | None = None
    error: str | None = None


@dataclass
class MigrationBatchResult:
    results: list[MigrationResult]
    uuid_collisions: dict | None = None


class MigrationFetchError(RuntimeError):
    """Could not read panel data (API blocked, bad credentials, missing backup)."""


class ThreeXUIClient:
    """Minimal 3x-ui API client (session cookie auth)."""

    def __init__(self, base_url: str, username: str, password: str, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self._session: requests.Session | None = None

    def __enter__(self):
        self._session = requests.Session()
        self.login()
        return self

    def __exit__(self, *args):
        if self._session:
            self._session.close()

    def login(self) -> None:
        assert self._session is not None
        # Warm session cookies (some panels require visiting / first).
        try:
            self._session.get(f"{self.base_url}/", timeout=self.timeout)
        except requests.RequestException:
            pass
        try:
            resp = self._session.post(
                f"{self.base_url}/login",
                data={"username": self.username, "password": self.password},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise MigrationFetchError(
                f"Cannot reach 3x-ui panel at {self.base_url}: {exc}"
            ) from exc
        if resp.status_code == 403:
            raise MigrationFetchError(
                f"3x-ui login blocked (HTTP 403) at {self.base_url}/login — "
                "the panel may whitelist IPs or block this server. "
                "Use a backup JSON file instead, or allow this server's IP on the source panel."
            )
        if resp.status_code == 404:
            raise MigrationFetchError(
                f"3x-ui login endpoint not found at {self.base_url}/login — "
                "check the panel URL/port or use a backup JSON file."
            )
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            raise MigrationFetchError(
                f"3x-ui login failed (HTTP {resp.status_code}) at {self.base_url}/login"
            ) from exc
        try:
            data = resp.json()
        except ValueError as exc:
            raise MigrationFetchError(
                f"3x-ui login returned non-JSON from {self.base_url}/login"
            ) from exc
        if data.get("success") is False:
            raise MigrationFetchError(data.get("msg") or "3x-ui login failed (bad username/password)")

    def get(self, path: str) -> Any:
        assert self._session is not None
        resp = self._session.get(f"{self.base_url}{path}", timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and data.get("success") is False:
            raise RuntimeError(data.get("msg") or f"3x-ui API error: {path}")
        return data.get("obj", data)


def _slugify_tag(panel_slug: str, tag: str) -> str:
    base = _TAG_SAFE.sub("-", (tag or "inbound").strip()).strip("-") or "inbound"
    prefix = _TAG_SAFE.sub("-", panel_slug.strip()).strip("-") or "panel"
    return f"{prefix}-{base}"[:64]


def _parse_panel_settings(raw: dict) -> dict:
    sub_uri = (
        raw.get("subURI") or raw.get("subUri") or raw.get("subDomain")
        or raw.get("sub_domain") or ""
    ).strip()
    sub_path = (raw.get("subPath") or raw.get("sub_path") or "/sub/").strip("/") or "sub"
    sub_port = raw.get("subPort") or raw.get("sub_port")
    sub_json = (
        raw.get("subJsonPath") or raw.get("subJsonURI") or raw.get("subJsonPath") or "json"
    ).strip("/") or "json"
    sub_clash = (raw.get("subClashPath") or raw.get("sub_clash_path") or "clash").strip("/") or "clash"

    host = None
    public_base = sub_uri.rstrip("/")
    if sub_uri:
        parsed = urlparse(sub_uri if "://" in sub_uri else f"https://{sub_uri}")
        host = (parsed.hostname or "").lower() or None
        if not public_base:
            public_base = f"https://{host}:{sub_port or 443}/{sub_path}".rstrip("/")

    listen_port = int(sub_port) if sub_port else None
    return {
        "host": host,
        "path_prefix": sub_path,
        "public_base_url": public_base,
        "listen_port": listen_port,
        "json_path": sub_json,
        "clash_path": sub_clash,
    }


def _load_backup(path: str) -> dict:
    from app.migration.postgres_dump import load_panel_from_postgres_dump
    from app.migration.sqlite_dump import backup_kind, load_panel_from_sqlite

    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(path)

    kind = backup_kind(p)
    if kind == "pg_custom":
        settings, inbounds, panel_obj = load_panel_from_postgres_dump(p)
        return {
            "settings": settings,
            "inbounds": inbounds,
            **panel_obj,
        }
    if kind in {"sql_dump", "sqlite_db"}:
        settings, inbounds, panel_obj = load_panel_from_sqlite(p)
        return {
            "settings": settings,
            "inbounds": inbounds,
            **panel_obj,
        }

    if p.suffix.lower() == ".json":
        text = p.read_text(encoding="utf-8", errors="replace")
        return json.loads(text)

    raise ValueError(
        f"Unsupported backup format: {p.name}. "
        "Use 3x-ui SQLite (.db), SQLite SQL dump, PostgreSQL pg_dump, or JSON export."
    )


def _load_backup_panel(source: PanelSource) -> tuple[dict, list[dict], dict]:
    backup = _load_backup(source.backup_path)
    panel_obj = backup if isinstance(backup, dict) else {}
    settings = panel_obj.get("settings") or panel_obj.get("panel") or {}
    if isinstance(settings, list):
        settings = {row.get("key"): row.get("value") for row in settings if isinstance(row, dict)}
    raw_inbounds = panel_obj.get("inbounds") or panel_obj.get("obj") or []
    if isinstance(raw_inbounds, dict):
        inbounds = list(raw_inbounds.values())
    elif isinstance(raw_inbounds, list):
        inbounds = raw_inbounds
    else:
        inbounds = []
    return settings, inbounds, panel_obj


def _fetch_panel_data(source: PanelSource) -> tuple[dict, list[dict], dict]:
    settings: dict = {}
    inbounds: list[dict] = []
    panel_obj: dict = {}

    if source.backup_path:
        try:
            settings, inbounds, panel_obj = _load_backup_panel(source)
        except FileNotFoundError as exc:
            raise MigrationFetchError(f"Backup file not found: {source.backup_path}") from exc
        except json.JSONDecodeError as exc:
            raise MigrationFetchError(f"Invalid backup JSON: {source.backup_path}") from exc
        except ValueError as exc:
            raise MigrationFetchError(str(exc)) from exc
    elif source.base_url:
        if not source.username or not source.password:
            raise MigrationFetchError(
                "Panel URL requires admin username and password, or provide backup_path instead."
            )
        try:
            with ThreeXUIClient(source.base_url, source.username, source.password) as client:
                settings_raw = client.get("/panel/setting/all") or {}
                settings = settings_raw if isinstance(settings_raw, dict) else {}
                inbounds_raw = client.get("/panel/inbound/list") or []
                inbounds = inbounds_raw if isinstance(inbounds_raw, list) else []
        except MigrationFetchError:
            raise
        except requests.RequestException as exc:
            raise MigrationFetchError(
                f"Cannot reach 3x-ui API at {source.base_url}: {exc}"
            ) from exc
        except Exception as exc:
            raise MigrationFetchError(str(exc)) from exc
    else:
        raise MigrationFetchError("Panel source requires base_url or backup_path")

    return settings, inbounds, panel_obj


def _failed_result(source: PanelSource, message: str) -> MigrationResult:
    return MigrationResult(
        panel_slug=source.slug,
        applied=False,
        endpoint={"slug": source.slug},
        error=message,
        warnings=[message],
    )


from app.user_import.parsers import parse_upload_with_meta


def _client_proxies(client: dict, inbound: dict) -> dict:
    protocol = str(inbound.get("protocol") or "vless").lower()
    uuid = client.get("id") or client.get("password") or client.get("uuid")
    flow = str(client.get("flow") or "").strip()
    if protocol in ("vless", "vmess", "trojan"):
        key = "id" if protocol != "trojan" else "password"
        settings: dict = {key: uuid}
        if flow and protocol in ("vless", "trojan"):
            settings["flow"] = flow
        return {protocol: settings}
    if protocol == "shadowsocks":
        return {"shadowsocks": {"password": client.get("password") or uuid, "method": client.get("method") or "chacha20-ietf-poly1305"}}
    return {}


def _ensure_migration_host(
    db: Session,
    inbound_tag: str,
    host: ProxyHostModel,
) -> bool:
    """Create or replace template host for a migrated inbound. Returns True if created."""
    inbound = crud.get_or_create_inbound(db, inbound_tag)
    existing = crud.get_hosts(db, inbound_tag)
    template_only = not existing or all(
        "{SERVER_IP}" in str(h.address or "") for h in existing
    )
    if template_only:
        crud.update_hosts(db, inbound_tag, [host])
        return True
    for row in existing:
        if str(row.address or "").lower() == str(host.address or "").lower():
            return False
    crud.add_host(db, inbound_tag, host)
    return True


def _persist_xray_inbounds(xray_config: dict) -> None:
    import commentjson
    from config import XRAY_JSON

    current: dict = {}
    try:
        with open(XRAY_JSON, "r", encoding="utf-8") as f:
            current = commentjson.loads(f.read())
    except OSError:
        current = {}
    merged = dict(current)
    by_tag = {row.get("tag"): row for row in merged.get("inbounds") or []}
    for row in xray_config.get("inbounds") or []:
        tag = row.get("tag")
        if tag:
            by_tag[tag] = row
    merged["inbounds"] = list(by_tag.values())
    from app import xray
    from app.xray.config import XRayConfig
    from app.xray.inbound_normalize import normalize_core_config_payload

    merged = normalize_core_config_payload(merged)
    xray.config = XRayConfig(merged, api_port=xray.config.api_port)
    with open(XRAY_JSON, "w", encoding="utf-8") as f:
        f.write(json.dumps(merged, indent=4))


def _cert_readable(path: str | None) -> bool:
    if not path:
        return False
    try:
        return os.path.isfile(path) and os.access(path, os.R_OK)
    except OSError:
        return False


def _resolve_migrated_tls_cert(server_name: str) -> tuple[str, str] | None:
    """Map legacy 3x-ui cert paths to panel-writable TLS material."""
    from app.xray.tls_presets import XRAY_TLS_DIR, discover_tls_certificates, generate_self_signed

    host = (server_name or "").strip().lower()
    for preset in discover_tls_certificates():
        sn = str(preset.get("serverName") or "").lower()
        cert = preset.get("certificateFile")
        key = preset.get("keyFile")
        if host and sn == host and _cert_readable(cert) and _cert_readable(key):
            return str(cert), str(key)

    safe = re.sub(r"[^a-zA-Z0-9._-]", "-", host or "migrated")[:64] or "migrated"
    cert_path = XRAY_TLS_DIR / f"{safe}.crt"
    key_path = XRAY_TLS_DIR / f"{safe}.key"
    if _cert_readable(str(cert_path)) and _cert_readable(str(key_path)):
        return str(cert_path), str(key_path)

    if host:
        try:
            generated = generate_self_signed(host)
            return str(generated["certificateFile"]), str(generated["keyFile"])
        except Exception as exc:
            logger.warning("Could not generate TLS cert for %s: %s", host, exc)
    return None


def _sanitize_migrated_stream_tls(stream: dict) -> list[str]:
    """Replace unreadable legacy cert paths from 3x-ui backups."""
    warnings: list[str] = []
    if not isinstance(stream, dict):
        return warnings
    if stream.get("security") != "tls":
        return warnings

    tls = stream.get("tlsSettings")
    if not isinstance(tls, dict):
        return warnings

    server_name = str(tls.get("serverName") or "").strip()
    certs = tls.get("certificates")
    if not isinstance(certs, list):
        return warnings

    for cert in certs:
        if not isinstance(cert, dict):
            continue
        cert_file = cert.get("certificateFile") or cert.get("certFile")
        key_file = cert.get("keyFile")
        if _cert_readable(cert_file) and _cert_readable(key_file):
            continue
        resolved = _resolve_migrated_tls_cert(server_name)
        if not resolved:
            stream["security"] = "none"
            stream.pop("tlsSettings", None)
            warnings.append(
                f"TLS disabled for {server_name or 'inbound'}: legacy cert {cert_file!r} is not readable on this server"
            )
            break
        cert["certificateFile"], cert["keyFile"] = resolved
        warnings.append(
            f"TLS cert for {server_name or 'inbound'} remapped to {resolved[0]} (legacy path was {cert_file!r})"
        )
    return warnings


def _listen_port_key(listen: str, port: int) -> tuple[str, int]:
    listen = str(listen or "0.0.0.0").strip() or "0.0.0.0"
    return listen, port


def _occupied_listen_ports(xray_config: dict, *, include_live: bool = False) -> set[tuple[str, int]]:
    occupied: set[tuple[str, int]] = set()
    for ib in xray_config.get("inbounds") or []:
        if not isinstance(ib, dict):
            continue
        raw_port = ib.get("port")
        if raw_port is None:
            continue
        try:
            port = int(raw_port)
        except (TypeError, ValueError):
            continue
        occupied.add(_listen_port_key(str(ib.get("listen") or "0.0.0.0"), port))
    if include_live:
        try:
            from app.xray.inbound_ports import listener_pids_by_port

            for port in listener_pids_by_port():
                occupied.add(_listen_port_key("0.0.0.0", port))
                occupied.add(_listen_port_key("127.0.0.1", port))
                occupied.add(_listen_port_key("::", port))
        except Exception:
            pass
    return occupied


def _find_free_listen_port(
    listen: str,
    desired: int,
    occupied: set[tuple[str, int]],
) -> int:
    listen = str(listen or "0.0.0.0").strip() or "0.0.0.0"
    start = max(desired, 1024) if listen in ("0.0.0.0", "::", "") else max(desired, 1)
    for candidate in range(start, 65536):
        if _listen_port_key(listen, candidate) not in occupied:
            return candidate
    for candidate in range(1024, start):
        if _listen_port_key(listen, candidate) not in occupied:
            return candidate
    raise ValueError(f"no free port on {listen} (wanted {desired})")


def _merge_inbound_to_xray(panel_slug: str, inbound: dict, xray_config: dict) -> str:
    """Return prefixed inbound tag after merge into xray config."""
    stream = inbound.get("streamSettings") or inbound.get("stream") or {}
    if isinstance(stream, str):
        try:
            stream = json.loads(stream)
        except json.JSONDecodeError:
            stream = {}
    tag = inbound.get("tag") or inbound.get("remark") or f"inbound-{inbound.get('id', '')}"
    new_tag = _slugify_tag(panel_slug, str(tag))

    entry = {
        "tag": new_tag,
        "protocol": inbound.get("protocol"),
        "port": inbound.get("port"),
        "listen": inbound.get("listen") or "0.0.0.0",
        "settings": inbound.get("settings"),
        "streamSettings": stream,
        "sniffing": inbound.get("sniffing"),
    }
    if isinstance(entry["settings"], str):
        try:
            entry["settings"] = json.loads(entry["settings"])
        except json.JSONDecodeError:
            entry["settings"] = {}
    if isinstance(entry["settings"], dict):
        # NexusPanel users live in the DB; do not embed 3x-ui client lists in Xray JSON.
        entry["settings"].pop("clients", None)
        if str(entry.get("protocol") or "").lower() == "vless":
            from app.xray.inbound_normalize import normalize_vless_inbound_settings

            normalize_vless_inbound_settings(entry["settings"])
    sniffing = entry.get("sniffing")
    if isinstance(sniffing, str):
        try:
            entry["sniffing"] = json.loads(sniffing)
        except json.JSONDecodeError:
            entry["sniffing"] = {}
    tls_warnings = _sanitize_migrated_stream_tls(entry.get("streamSettings") or {})
    port = entry.get("port")
    listen = str(entry.get("listen") or "0.0.0.0")
    try:
        port_num = int(port)
    except (TypeError, ValueError):
        port_num = 0
    if port_num > 0 and port_num < 1024 and listen in ("0.0.0.0", "::", ""):
        entry["listen"] = "127.0.0.1"
        if port_num == 443:
            entry["port"] = 10443
            tls_warnings.append(
                f"Inbound {new_tag}: moved TLS gRPC from 0.0.0.0:443 to 127.0.0.1:10443 "
                "(port 443 is used by nginx / requires root). Point nginx grpc_pass here if needed."
            )
        else:
            tls_warnings.append(
                f"Inbound {new_tag}: listen set to 127.0.0.1 (privileged port {port_num} cannot bind as panel user)"
            )
    occupied = _occupied_listen_ports(xray_config, include_live=True)
    listen = str(entry.get("listen") or "0.0.0.0")
    try:
        port_num = int(entry.get("port") or 0)
    except (TypeError, ValueError):
        port_num = 0
    if port_num > 0:
        key = _listen_port_key(listen, port_num)
        if key in occupied:
            new_port = _find_free_listen_port(listen, port_num + 1, occupied)
            tls_warnings.append(
                f"Inbound {new_tag}: port {port_num} on {listen} already used by another inbound; "
                f"remapped to {new_port}. Update nginx upstream if this panel needs a public listener."
            )
            entry["port"] = new_port
    existing = xray_config.setdefault("inbounds", [])
    replaced = False
    for i, row in enumerate(existing):
        if row.get("tag") == new_tag:
            existing[i] = entry
            replaced = True
            break
    if not replaced:
        existing.append(entry)
    return new_tag, tls_warnings


def _clients_from_inbound(inbound: dict) -> list[dict]:
    settings = inbound.get("settings") or {}
    if isinstance(settings, str):
        try:
            settings = json.loads(settings)
        except json.JSONDecodeError:
            settings = {}
    clients = settings.get("clients") or inbound.get("clients") or []
    return clients if isinstance(clients, list) else []


def preview_panel(db: Session, source: PanelSource) -> MigrationResult:
    try:
        settings, inbounds, _ = _fetch_panel_data(source)
    except MigrationFetchError as exc:
        return _failed_result(source, str(exc))
    sub = _parse_panel_settings(settings if settings else {})
    preview = MigrationResult(
        panel_slug=source.slug,
        applied=False,
        endpoint={
            "slug": source.slug,
            "host": sub["host"],
            "path_prefix": sub["path_prefix"],
            "public_base_url": sub["public_base_url"],
            "listen_port": sub["listen_port"],
            "export_mode": SubscriptionExportMode.full.value,
            "legacy_panel_id": source.legacy_panel_id or source.slug,
        },
    )

    for inbound in inbounds:
        tag = _slugify_tag(source.slug, str(inbound.get("tag") or inbound.get("remark") or ""))
        preview.inbound_tags.append(tag)
        for client in _clients_from_inbound(inbound):
            preview.user_count += 1
            if client.get("subId") or client.get("sub_id"):
                preview.alias_count += 1

    if sub.get("json_path") and sub["json_path"] != sub["path_prefix"]:
        preview.warnings.append(f"Additional json subscription path: /{sub['json_path']}/")
    if sub.get("clash_path") and sub["clash_path"] != sub["path_prefix"]:
        preview.warnings.append(f"Additional clash subscription path: /{sub['clash_path']}/")

    if crud.get_subscription_endpoint_by_slug(db, source.slug):
        preview.warnings.append(f"Endpoint slug '{source.slug}' already exists — run will update/merge")
    else:
        existing = crud.get_subscription_endpoint_by_host_path(
            db, sub["host"], sub["path_prefix"], enabled_only=False
        )
        if existing:
            preview.warnings.append(
                f"Host/path already registered as slug '{existing.slug}' — "
                f"run will update that endpoint (requested slug '{source.slug}' ignored for URL route)"
            )
    if len(source.slug) > 20:
        preview.warnings.append(
            f"Slug '{source.slug}' is long — use a short slug (e.g. sr1) so usernames stay unique"
        )
    return preview


def run_panel_migration(db: Session, source: PanelSource, *, dry_run: bool = False) -> MigrationResult:
    preview = preview_panel(db, source)
    if preview.error or dry_run:
        return preview

    try:
        return _apply_panel_migration(db, source, preview)
    except Exception as exc:
        logger.exception("Migration failed for panel %s", source.slug)
        preview.error = str(exc)
        preview.warnings.append(str(exc))
        return preview


def _apply_panel_migration(db: Session, source: PanelSource, preview: MigrationResult) -> MigrationResult:
    settings, inbounds, _ = _fetch_panel_data(source)
    sub = _parse_panel_settings(settings if settings else {})

    ep_data = {
        "slug": source.slug,
        "host": sub["host"],
        "path_prefix": sub["path_prefix"],
        "public_base_url": sub["public_base_url"],
        "listen_port": sub["listen_port"],
        "export_mode": SubscriptionExportMode.full.value,
        "legacy_panel_id": source.legacy_panel_id or source.slug,
        "enabled": True,
    }
    ep, _ = crud.upsert_subscription_endpoint(db, ep_data)
    if ep.slug != source.slug:
        preview.warnings.append(
            f"Subscription route kept slug '{ep.slug}' for {sub['host']}/{sub['path_prefix']}"
        )

    extra_paths = []
    if sub.get("json_path") and sub["json_path"] != sub["path_prefix"]:
        extra_paths.append((sub["json_path"], "v2ray-json"))
    if sub.get("clash_path") and sub["clash_path"] != sub["path_prefix"]:
        extra_paths.append((sub["clash_path"], "clash-meta"))

    for path_prefix, fmt in extra_paths:
        slug = f"{source.slug}-{path_prefix}"
        data = {
            "slug": slug,
            "host": sub["host"],
            "path_prefix": path_prefix,
            "public_base_url": f"{sub['public_base_url'].rsplit('/', 1)[0]}/{path_prefix}".rstrip("/"),
            "listen_port": sub["listen_port"],
            "export_mode": SubscriptionExportMode.full.value,
            "format_default": fmt,
            "legacy_panel_id": source.legacy_panel_id or source.slug,
            "enabled": True,
        }
        extra, _ = crud.upsert_subscription_endpoint(db, data)
        if extra.slug != slug:
            preview.warnings.append(
                f"Subscription route kept slug '{extra.slug}' for {sub['host']}/{path_prefix}"
            )

    from copy import deepcopy

    from app import xray

    xray_config = deepcopy(dict(xray.config))
    tag_map: dict[str, str] = {}
    for inbound in inbounds:
        old_tag = str(inbound.get("tag") or inbound.get("remark") or "")
        new_tag, tls_warnings = _merge_inbound_to_xray(source.slug, inbound, xray_config)
        preview.warnings.extend(tls_warnings)
        tag_map[old_tag] = new_tag
        if inbound.get("id") is not None:
            tag_map[str(inbound.get("id"))] = new_tag

    from app.migration.host_builder import build_migration_host

    for inbound in inbounds:
        new_tag = _slugify_tag(source.slug, str(inbound.get("tag") or inbound.get("remark") or ""))
        host = build_migration_host(
            panel_slug=source.slug,
            inbound_tag=new_tag,
            inbound=inbound,
            subscription_host=sub.get("host"),
        )
        if host and _ensure_migration_host(db, new_tag, host):
            preview.hosts_created += 1

    if xray_config.get("inbounds"):
        try:
            _persist_xray_inbounds(xray_config)
        except Exception as exc:
            preview.warnings.append(f"Xray config merge skipped: {exc}")

    from app.db.models import ProxyInbound as _ProxyInbound

    # Shared lookaside cache: the inbound set is effectively static for the
    # whole batch, so avoid a SELECT + session-autoflush per excluded-inbound
    # lookup (that per-row DB round trip against an ever-growing uncommitted
    # transaction was the dominant cost of multi-minute migrations).
    inbound_cache: dict[str, _ProxyInbound] = {
        row.tag: row for row in db.query(_ProxyInbound).all()
    }
    # Preload the sets we'd otherwise probe once per client (a SELECT-per-user on
    # a large, still-uncommitted transaction dominated import time). Existing
    # usernames tell us create-vs-update without a lookup; existing alias tokens
    # on this endpoint let a fresh import skip the per-alias existence SELECT.
    from app.db.models import SubscriptionTokenAlias as _STAlias
    from app.db.models import User as _DBUser

    existing_usernames: set[str] = {u for (u,) in db.query(_DBUser.username).all()}
    existing_alias_tokens: set[str] = {
        tok for (tok,) in db.query(_STAlias.token).filter(_STAlias.endpoint_id == ep.id).all()
    }
    processed = 0
    _COMMIT_BATCH_SIZE = 300

    # 3x-ui stores one client row per (inbound, subscriber), and a single
    # subscriber normally appears in several inbounds under the SAME subId.
    # Importing inbound-by-inbound used to create the user from the first
    # inbound it was seen in and then merely *status-update* them for every
    # other inbound — silently dropping all their other protocols/inbounds, so
    # a subscription that served vless+vmess+trojan came across with a single
    # protocol. Group every client by its resolved panel username first and
    # merge all of their protocols, inbound tags and traffic so nothing is lost.
    from collections import OrderedDict

    grouped: "OrderedDict[str, dict]" = OrderedDict()
    for inbound in inbounds:
        new_tag = _slugify_tag(source.slug, str(inbound.get("tag") or inbound.get("remark") or ""))
        for client in _clients_from_inbound(inbound):
            email = str(client.get("email") or client.get("id") or "").strip()
            if not email:
                continue
            username = _migration_username(source.slug, email, client)

            expire_raw = int(client.get("expiryTime") or client.get("expire") or 0)
            expire = expire_raw // 1000 if expire_raw > 1_000_000_000_000 else expire_raw
            total_raw = float(client.get("totalGB") or client.get("total") or 0)
            data_limit = int(total_raw * 1024**3) if 0 < total_raw < 10_000 else int(total_raw)
            used = int(client.get("up") or 0) + int(client.get("down") or 0)
            enabled = bool(client.get("enable", True))
            sub_id = str(client.get("subId") or client.get("sub_id") or "").strip()

            pu = grouped.get(username)
            if pu is None:
                pu = {
                    "username": username,
                    "proxies": {},   # proto -> settings dict
                    "inbounds": {},  # proto -> list[str] tags
                    "expire": 0,
                    "data_limit": 0,
                    "used": 0,
                    "any_enabled": False,
                    "sub_id": "",
                }
                grouped[username] = pu

            for p_type, p_settings in _client_proxies(client, inbound).items():
                pu["proxies"].setdefault(p_type, p_settings)
                tags = pu["inbounds"].setdefault(p_type, [])
                if new_tag and new_tag not in tags:
                    tags.append(new_tag)

            # Most-permissive expiry/limit, summed traffic, enabled if enabled on
            # any inbound (3x-ui tracks enable + up/down per inbound per client).
            pu["expire"] = max(pu["expire"], expire) if (pu["expire"] and expire) else (pu["expire"] or expire)
            pu["data_limit"] = (
                max(pu["data_limit"], data_limit)
                if (pu["data_limit"] and data_limit)
                else (pu["data_limit"] or data_limit)
            )
            pu["used"] += used
            pu["any_enabled"] = pu["any_enabled"] or enabled
            if sub_id and not pu["sub_id"]:
                pu["sub_id"] = sub_id

    for pu in grouped.values():
        username = pu["username"]
        status = UserStatus.active if pu["any_enabled"] else UserStatus.disabled
        proxies = pu["proxies"]
        inbounds_map = {proto: tags for proto, tags in pu["inbounds"].items() if tags}

        try:
            # A SAVEPOINT per user isolates a single malformed client (e.g. an
            # incompatible inbound/settings combo) so it rolls back only that
            # user instead of aborting — and losing — the entire panel import.
            with db.begin_nested():
                existing = crud.get_user(db, username) if username in existing_usernames else None
                if existing is not None:
                    crud.update_user(
                        db,
                        existing,
                        UserModify(
                            status=status,
                            expire=pu["expire"] or None,
                            data_limit=pu["data_limit"] or None,
                            proxies=proxies,
                            inbounds=inbounds_map,
                        ),
                        commit=False,
                        inbound_cache=inbound_cache,
                    )
                    if pu["used"] > 0:
                        existing.used_traffic = pu["used"]
                    user_id = existing.id
                    was_created = False
                else:
                    created = crud.create_user(
                        db,
                        UserCreate(
                            username=username,
                            status=UserStatusCreate.active,
                            expire=pu["expire"] or None,
                            data_limit=pu["data_limit"] or None,
                            proxies=proxies,
                            inbounds=inbounds_map,
                        ),
                        commit=False,
                        inbound_cache=inbound_cache,
                    )
                    if status == UserStatus.disabled:
                        crud.update_user(
                            db, created, UserModify(status=UserStatus.disabled),
                            commit=False, inbound_cache=inbound_cache,
                        )
                    if pu["used"] > 0:
                        created.used_traffic = pu["used"]
                    user_id = created.id
                    was_created = True
                    existing_usernames.add(username)

                alias_added = False
                if pu["sub_id"] and user_id:
                    if pu["sub_id"] in existing_alias_tokens:
                        # Already routed on this endpoint (re-run) — repoint it.
                        crud.upsert_subscription_token_alias(
                            db,
                            token=pu["sub_id"],
                            user_id=user_id,
                            endpoint_id=ep.id,
                            source="3x-ui-migration",
                            commit=False,
                        )
                    else:
                        # Fresh route — insert directly, skipping the existence SELECT.
                        crud.create_subscription_token_alias(
                            db,
                            {
                                "token": pu["sub_id"],
                                "user_id": user_id,
                                "endpoint_id": ep.id,
                                "source": "3x-ui-migration",
                            },
                            commit=False,
                        )
                        existing_alias_tokens.add(pu["sub_id"])
                    alias_added = True
        except Exception as exc:
            logger.warning("Migration: skipped user %s: %s", username, exc)
            preview.warnings.append(f"Skipped user '{username}': {exc}")
            continue

        if was_created:
            preview.users_created += 1
        else:
            preview.users_updated += 1
        if alias_added:
            preview.aliases_created += 1

        processed += 1
        if processed % _COMMIT_BATCH_SIZE == 0:
            # Bound session/transaction growth — SQLAlchemy's autoflush cost on
            # every subsequent query scales with the number of pending objects,
            # so one giant transaction for the whole panel degrades
            # quadratically on large imports.
            db.commit()

    db.commit()

    from app.migration.validation import validate_panel_import

    validation = validate_panel_import(
        db,
        inbounds=inbounds,
        panel_slug=source.slug,
        inbound_tags=preview.inbound_tags,
        users_created=preview.users_created,
        users_updated=preview.users_updated,
        aliases_created=preview.aliases_created,
        hosts_created=preview.hosts_created,
        endpoint_id=ep.id,
    )
    preview.validation = validation.to_dict()
    if not validation.passed:
        preview.warnings.extend(validation.errors)

    preview.applied = True
    return preview


def run_batch(
    db: Session,
    sources: list[PanelSource],
    *,
    dry_run: bool = False,
) -> MigrationBatchResult:
    from app.migration.collisions import detect_uuid_collisions
    from app.migration.state import migration_context

    exports: list[tuple[str, list[dict]]] = []
    fetch_errors: dict[str, str] = {}
    for src in sources:
        try:
            _, inbounds, _ = _fetch_panel_data(src)
            exports.append((src.slug, inbounds))
        except MigrationFetchError as exc:
            fetch_errors[src.slug] = str(exc)

    collision_report = detect_uuid_collisions(exports)
    results: list[MigrationResult] = []

    if collision_report.has_conflicts and not dry_run:
        summary = (
            f"UUID collision across panels ({len(collision_report.collisions)} conflict(s)) — "
            "resolve manually per panel.md §6.0 before import"
        )
        for src in sources:
            if src.slug in fetch_errors:
                results.append(_failed_result(src, fetch_errors[src.slug]))
                continue
            preview = preview_panel(db, src)
            preview.error = summary
            preview.warnings.append(summary)
            for hit in collision_report.collisions:
                if hit.first_panel == src.slug or hit.second_panel == src.slug:
                    preview.warnings.append(
                        f"UUID {hit.uuid} shared between {hit.first_panel} and {hit.second_panel}"
                    )
            results.append(preview)
        return MigrationBatchResult(
            results=results,
            uuid_collisions=collision_report.to_dict(),
        )

    with migration_context():
        for src in sources:
            if src.slug in fetch_errors:
                results.append(_failed_result(src, fetch_errors[src.slug]))
                continue
            result = run_panel_migration(db, src, dry_run=dry_run)
            if collision_report.has_conflicts:
                for hit in collision_report.collisions:
                    if hit.first_panel == src.slug or hit.second_panel == src.slug:
                        result.warnings.append(
                            f"UUID {hit.uuid} shared between {hit.first_panel} and {hit.second_panel} "
                            "(informational — import proceeds; same person on multiple servers)"
                        )
            results.append(result)

    return MigrationBatchResult(
        results=results,
        uuid_collisions=collision_report.to_dict() if collision_report.has_conflicts else None,
    )
