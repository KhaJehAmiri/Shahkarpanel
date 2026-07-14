"""Parse 3x-ui SQLite backups (.db) and portable SQL dumps (.dump/.sql)."""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Protocol

_SQLITE_MAGIC = b"SQLite format 3\x00"
_PGDMP_MAGIC = b"PGDMP"
_SHELL_LINE = re.compile(r"^\\")


def backup_kind(path: Path) -> str:
    if not path.is_file():
        return "unknown"
    head = path.read_bytes()[:16]
    if head.startswith(_SQLITE_MAGIC):
        return "sqlite_db"
    if head[:5] == _PGDMP_MAGIC:
        return "pg_custom"
    suffix = path.suffix.lower()
    if suffix in {".db", ".sqlite", ".sqlite3"}:
        return "sqlite_db"
    if suffix in {".dump", ".sql"}:
        sample = path.read_bytes()[:4096].lstrip()
        if b"\x00" in sample[:256]:
            return "unknown"
        if sample.startswith((b"PRAGMA", b"BEGIN", b"CREATE", b"INSERT", b"COMMIT", b"--", b"/*")):
            return "sql_dump"
        return "unknown"
    if head.lstrip().startswith((b"PRAGMA", b"BEGIN", b"CREATE", b"INSERT", b"COMMIT")):
        return "sql_dump"
    return "unknown"


class _PanelTableAccess(Protocol):
    def table_exists(self, name: str) -> bool: ...

    def rows(self, table: str) -> list[dict[str, Any]]: ...


class _SqlitePanelTables:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def table_exists(self, name: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (name,),
        ).fetchone()
        return row is not None

    def rows(self, table: str) -> list[dict[str, Any]]:
        if not self.table_exists(table):
            return []
        cols = [row[1] for row in self._conn.execute(f"PRAGMA table_info({table})")]
        cur = self._conn.execute(f"SELECT * FROM {table}")
        return [{cols[i]: row[i] for i in range(len(cols))} for row in cur.fetchall()]


def _clean_sql_dump(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if not line.strip():
            continue
        if _SHELL_LINE.match(line.strip()):
            continue
        lines.append(line)
    return "\n".join(lines)


def open_sqlite_backup(path: str | Path) -> sqlite3.Connection:
    """Open a 3x-ui .db file or restore a .dump/.sql into an in-memory SQLite DB."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(str(p))

    kind = backup_kind(p)
    if kind == "sqlite_db":
        return sqlite3.connect(f"file:{p}?mode=ro", uri=True)

    if kind == "sql_dump":
        sql = _clean_sql_dump(p.read_text(encoding="utf-8", errors="replace"))
        conn = sqlite3.connect(":memory:")
        try:
            conn.executescript(sql)
        except sqlite3.Error as exc:
            conn.close()
            raise ValueError(f"Invalid 3x-ui SQL dump ({p.name}): {exc}") from exc
        return conn

    raise ValueError(
        f"Unsupported backup format: {p.name}. "
        "Expected 3x-ui SQLite (.db), SQLite SQL dump, PostgreSQL pg_dump (.dump), or JSON export."
    )


def _parse_json_field(raw: Any, default: Any) -> Any:
    if raw is None:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return default
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return default
    return default


def _client_from_record(rec: dict[str, Any], traffic: dict[str, Any] | None = None) -> dict[str, Any]:
    email = rec.get("email") or rec.get("Email") or ""
    client_id = rec.get("uuid") or rec.get("UUID") or rec.get("id") or ""
    sub_id = rec.get("sub_id") or rec.get("subId") or rec.get("SubID") or ""
    up = int(rec.get("up") or 0)
    down = int(rec.get("down") or 0)
    total_gb = rec.get("total_gb") or rec.get("totalGB") or rec.get("TotalGB") or 0
    expiry = rec.get("expiry_time") or rec.get("expiryTime") or rec.get("ExpiryTime") or 0
    enable = rec.get("enable")
    if enable is None:
        enable = rec.get("Enable", True)

    if traffic:
        up = int(traffic.get("up") or up or 0)
        down = int(traffic.get("down") or down or 0)
        total_gb = traffic.get("total") or traffic.get("total_gb") or total_gb
        expiry = traffic.get("expiry_time") or traffic.get("expiryTime") or expiry
        if traffic.get("enable") is not None:
            enable = traffic.get("enable")

    return {
        "email": email,
        "id": str(client_id),
        "subId": sub_id,
        "password": rec.get("password") or rec.get("Password") or "",
        "flow": rec.get("flow") or rec.get("Flow") or "",
        "enable": bool(enable),
        "expiryTime": int(expiry or 0),
        "totalGB": int(total_gb or 0),
        "up": up,
        "down": down,
        "limitIp": int(rec.get("limit_ip") or rec.get("limitIp") or 0),
        "comment": rec.get("comment") or rec.get("Comment") or "",
    }


def _traffic_by_email(tables: _PanelTableAccess) -> dict[str, dict[str, Any]]:
    table = "client_traffics" if tables.table_exists("client_traffics") else None
    if not table and tables.table_exists("client_traffic"):
        table = "client_traffic"
    if not table:
        return {}
    merged: dict[str, dict[str, Any]] = {}
    for row in tables.rows(table):
        email = row.get("email") or row.get("Email") or ""
        if not email:
            continue
        prev = merged.get(email, {})
        prev_up = int(prev.get("up") or 0)
        prev_down = int(prev.get("down") or 0)
        new_up = int(row.get("up") or 0)
        new_down = int(row.get("down") or 0)
        # Prefer MAX, not SUM. 3x-ui often has one client_traffics row per
        # inbound for the same email, each carrying the same cumulative
        # up/down. Summing those duplicates doubled (or tripled) used traffic
        # on import. Distinct per-inbound meters with the same email are
        # unusual; max keeps the higher shared counter.
        merged[email] = {
            "up": max(prev_up, new_up),
            "down": max(prev_down, new_down),
            "total": row.get("total") or row.get("Total") or prev.get("total"),
            "expiry_time": row.get("expiry_time") or row.get("expiryTime") or prev.get("expiry_time"),
            "enable": row.get("enable") if row.get("enable") is not None else prev.get("enable"),
        }
    return merged


def _load_settings(tables: _PanelTableAccess) -> dict[str, Any]:
    settings: dict[str, Any] = {}
    for row in tables.rows("settings"):
        key = row.get("key") or row.get("Key")
        if key is None:
            continue
        settings[str(key)] = row.get("value") or row.get("Value") or ""
    return settings


def _inbound_row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    settings_raw = row.get("settings") or row.get("Settings") or "{}"
    stream = row.get("stream_settings") or row.get("streamSettings") or row.get("StreamSettings") or "{}"
    sniffing = row.get("sniffing") or row.get("Sniffing") or "{}"
    tag = row.get("tag") or row.get("Tag") or row.get("remark") or row.get("Remark") or ""
    return {
        "id": row.get("id") or row.get("Id"),
        "tag": tag,
        "remark": row.get("remark") or row.get("Remark") or tag,
        "protocol": row.get("protocol") or row.get("Protocol") or "vless",
        "port": row.get("port") or row.get("Port") or 0,
        "listen": row.get("listen") or row.get("Listen") or "0.0.0.0",
        "enable": row.get("enable") if row.get("enable") is not None else row.get("Enable", True),
        "settings": settings_raw if isinstance(settings_raw, str) else json.dumps(settings_raw),
        "streamSettings": stream if isinstance(stream, str) else json.dumps(stream),
        "sniffing": sniffing if isinstance(sniffing, str) else json.dumps(sniffing),
    }


def _attach_relational_clients(
    inbounds_by_id: dict[int, dict[str, Any]],
    tables: _PanelTableAccess,
    traffic_by_email: dict[str, dict[str, Any]],
) -> None:
    if not tables.table_exists("clients"):
        return
    clients_by_id: dict[int, dict[str, Any]] = {}
    for rec in tables.rows("clients"):
        cid = rec.get("id") or rec.get("Id")
        if cid is None:
            continue
        email = rec.get("email") or rec.get("Email") or ""
        traffic = traffic_by_email.get(str(email))
        clients_by_id[int(cid)] = _client_from_record(rec, traffic)

    if not tables.table_exists("client_inbounds"):
        return

    links_by_inbound: dict[int, list[int]] = {}
    for link in tables.rows("client_inbounds"):
        cid = link.get("client_id") or link.get("clientId") or link.get("ClientId")
        iid = link.get("inbound_id") or link.get("inboundId") or link.get("InboundId")
        if cid is None or iid is None:
            continue
        links_by_inbound.setdefault(int(iid), []).append(int(cid))

    for iid, client_ids in links_by_inbound.items():
        inbound = inbounds_by_id.get(iid)
        if not inbound:
            continue
        settings = _parse_json_field(inbound.get("settings"), {})
        clients = settings.get("clients")
        if not isinstance(clients, list):
            clients = []
        seen = {str(c.get("email")) for c in clients if isinstance(c, dict) and c.get("email")}
        changed = False
        for cid in client_ids:
            client = clients_by_id.get(cid)
            if not client:
                continue
            email = str(client.get("email") or "")
            if email and email not in seen:
                clients.append(client)
                seen.add(email)
                changed = True
        if changed:
            settings["clients"] = clients
            inbound["settings"] = json.dumps(settings)


def _merge_traffic_into_legacy_clients(
    inbounds: list[dict[str, Any]],
    traffic_by_email: dict[str, dict[str, Any]],
) -> None:
    for inbound in inbounds:
        settings = _parse_json_field(inbound.get("settings"), {})
        clients = settings.get("clients")
        if not isinstance(clients, list):
            continue
        changed = False
        for i, raw in enumerate(clients):
            if not isinstance(raw, dict):
                continue
            email = raw.get("email") or raw.get("Email") or ""
            traffic = traffic_by_email.get(str(email))
            if not traffic:
                continue
            merged = _client_from_record(raw, traffic)
            clients[i] = merged
            changed = True
        if changed:
            settings["clients"] = clients
            inbound["settings"] = json.dumps(settings)


def load_panel_from_tables(
    tables: _PanelTableAccess,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Return (settings, inbounds, panel_obj) from 3x-ui table data."""
    settings = _load_settings(tables)
    traffic_by_email = _traffic_by_email(tables)

    inbound_rows = tables.rows("inbounds")
    if not inbound_rows:
        raise ValueError("No inbounds table/data found in 3x-ui backup")

    inbounds_by_id: dict[int, dict[str, Any]] = {}
    inbounds: list[dict[str, Any]] = []
    for row in inbound_rows:
        inbound = _inbound_row_to_dict(row)
        iid = inbound.get("id")
        if iid is not None:
            inbounds_by_id[int(iid)] = inbound
        inbounds.append(inbound)

    _attach_relational_clients(inbounds_by_id, tables, traffic_by_email)
    _merge_traffic_into_legacy_clients(inbounds, traffic_by_email)

    panel_obj = {
        "settings": settings,
        "inbounds": inbounds,
    }
    return settings, inbounds, panel_obj


def load_panel_from_sqlite(path: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Return (settings, inbounds, panel_obj) from a 3x-ui SQLite backup."""
    conn = open_sqlite_backup(path)
    try:
        settings, inbounds, panel_obj = load_panel_from_tables(_SqlitePanelTables(conn))
        panel_obj["source"] = "3x-ui-sqlite"
        panel_obj["backup_path"] = str(path)
        return settings, inbounds, panel_obj
    finally:
        conn.close()


def migrations_upload_dir() -> Path:
    import os

    from config import BACKUP_DIR

    custom = (os.environ.get("NEXUSPANEL_MIGRATIONS_DIR") or "").strip()
    if custom:
        return Path(custom)
    return Path(BACKUP_DIR) / "migrations"


def save_uploaded_backup(content: bytes, filename: str) -> str:
    """Persist an uploaded 3x-ui backup under the panel-writable migrations dir."""
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", filename).strip("-") or "backup.dump"
    dest_dir = migrations_upload_dir()
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / safe
        dest.write_bytes(content)
    except OSError as exc:
        raise OSError(
            f"Cannot write backup to {dest_dir} ({exc}). "
            "Ensure the directory is writable by the nexuspanel user."
        ) from exc
    return str(dest)
