"""Parse exports from Marzban, PasarGuard/Remnawave, 3x-ui, CSV, and share-link dumps."""
from __future__ import annotations

import base64
import csv
import io
import json
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

_DUMP_SUFFIXES = {".dump", ".sql", ".db", ".sqlite", ".sqlite3"}
_SQLITE_MAGIC = b"SQLite format 3\x00"
_PGDMP_MAGIC = b"PGDMP"

USERNAME_RE = re.compile(r"^(?=\w{3,32}\b)[a-zA-Z0-9-_@.]+(?:_[a-zA-Z0-9-_@.]+)*$")

PROTO_ALIASES = {
    "vless": "vless",
    "vmess": "vmess",
    "trojan": "trojan",
    "shadowsocks": "shadowsocks",
    "ss": "shadowsocks",
    "socks": "socks",
    "http": "http",
    "wireguard": "wireguard",
}


@dataclass
class ParseResult:
    rows: List[Dict[str, Any]]
    source: str = "unknown"
    format_hint: str = ""
    warnings: List[str] = field(default_factory=list)


def _parse_expire(raw: Any) -> int:
    if raw is None or raw == "" or raw == 0:
        return 0
    try:
        v = int(float(raw))
        if v > 1_000_000_000_000:
            return v // 1000
        return v
    except (TypeError, ValueError):
        return 0


def _parse_limit_bytes(raw: Any) -> int:
    if raw is None or raw == "":
        return 0
    try:
        v = float(raw)
        if v <= 0:
            return 0
        if v < 10_000:
            return int(v * 1024**3)
        return int(v)
    except (TypeError, ValueError):
        return 0


def _map_status(raw: Any) -> str:
    if raw is None:
        return "active"
    if isinstance(raw, bool):
        return "active" if raw else "disabled"
    s = str(raw).strip().lower()
    if s in ("0", "false", "disabled", "off", "inactive"):
        return "disabled"
    if s in ("on_hold", "on hold", "onhold"):
        return "on_hold"
    return "active"


def _normalize_proxies(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        out: Dict[str, Any] = {}
        for k, v in raw.items():
            key = PROTO_ALIASES.get(str(k).lower(), str(k).lower())
            if key in PROTO_ALIASES.values() or key in ("vless", "vmess", "trojan", "shadowsocks", "wireguard"):
                out[key] = v if isinstance(v, dict) else {}
        return out
    return {}


def _normalize_inbounds(raw: Any) -> Dict[str, List[str]]:
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, List[str]] = {}
    for key, tags in raw.items():
        proto = PROTO_ALIASES.get(str(key).lower(), str(key).lower())
        if isinstance(tags, list):
            out[proto] = [str(t) for t in tags if t]
        elif isinstance(tags, str) and tags:
            out[proto] = [tags]
    return out


def _sanitize_username(raw: str, source: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    if "@" in s and source in ("3x-ui", "links", "csv"):
        s = s.split("@", 1)[0]
    s = re.sub(r"[^a-zA-Z0-9-_@.]", "_", s).strip("._")
    if len(s) < 3:
        s = f"u_{s}" if s else ""
    if len(s) > 32:
        s = s[:32]
    if s and not USERNAME_RE.match(s):
        s = re.sub(r"[^a-zA-Z0-9-_]", "_", s)[:32]
    return s if s and USERNAME_RE.match(s) else ""


def _parse_used_bytes(u: Dict[str, Any]) -> int:
    """3x-ui stores upload/download counters in bytes (``up`` + ``down``)."""
    try:
        used = int(u.get("used_traffic") or u.get("used") or 0)
    except (TypeError, ValueError):
        used = 0
    try:
        up = int(u.get("up") or 0)
        down = int(u.get("down") or 0)
    except (TypeError, ValueError):
        up = down = 0
    return max(used, up + down)


def _normalize_user(u: Dict[str, Any], source: str = "marzban") -> Dict[str, Any]:
    raw_name = (u.get("username") or u.get("email") or u.get("name") or u.get("id") or "").strip()
    if isinstance(raw_name, (int, float)):
        raw_name = str(int(raw_name))
    username = _sanitize_username(str(raw_name), source)
    if not username and u.get("uuid"):
        username = _sanitize_username(str(u["uuid"]).replace("-", "")[:12], source)
    if not username and u.get("id"):
        username = _sanitize_username(f"uid_{u['id']}", source)

    sub_id, email = _extract_3x_identity(u) if source == "3x-ui" else ("", "")
    note = (u.get("note") or u.get("comment") or u.get("desc") or "").strip()
    if email and "3x-ui:" not in note:
        note = (f"3x-ui: {email}" + (f" | {note}" if note else "")).strip()[:500]
    else:
        note = note[:500]

    return {
        "username": username,
        "data_limit": _parse_limit_bytes(
            u.get("data_limit") or u.get("totalGB") or u.get("total_gb") or u.get("total") or u.get("volume")
        ),
        "used_traffic": _parse_used_bytes(u),
        "expire": _parse_expire(
            u.get("expire") or u.get("expiryTime") or u.get("expiry") or u.get("expired_date")
        ),
        "note": note,
        "status": _map_status(u.get("status") if "status" in u else u.get("enable")),
        "proxies": _normalize_proxies(u.get("proxies") or _infer_proxies_from_3x(u)),
        "inbounds": _normalize_inbounds(u.get("inbounds") or {}),
        "sub_id": sub_id or None,
        "email": email or None,
        "conflict": None,
        "source": source,
    }


def _proxies_for_3x_client(client: Dict[str, Any], proto: str) -> Dict[str, Any]:
    """Keep original 3x-ui UUID / password so configs stay connected after import."""
    proto = PROTO_ALIASES.get(str(proto or "").lower(), str(proto or "").lower())
    client_id = client.get("id") or client.get("uuid")
    password = client.get("password")
    flow = client.get("flow") or ""
    if proto == "vless":
        settings: Dict[str, Any] = {}
        if client_id:
            settings["id"] = str(client_id)
        if flow:
            settings["flow"] = flow
        return {"vless": settings}
    if proto == "vmess":
        settings = {}
        if client_id:
            settings["id"] = str(client_id)
        return {"vmess": settings}
    if proto == "trojan":
        settings = {}
        if password:
            settings["password"] = str(password)
        return {"trojan": settings}
    if proto == "shadowsocks":
        settings = {
            "method": client.get("method") or "chacha20-ietf-poly1305",
        }
        if password:
            settings["password"] = str(password)
        return {"shadowsocks": settings}
    return _infer_proxies_from_3x({**client, "protocol": proto})


def _infer_proxies_from_3x(u: Dict[str, Any]) -> Dict[str, Any]:
    proxies: Dict[str, Any] = {}
    proto = PROTO_ALIASES.get(str(u.get("protocol") or u.get("type") or "").lower(), "")
    client_id = u.get("id") or u.get("uuid")
    password = u.get("password")
    flow = u.get("flow") or ""
    if proto:
        return _proxies_for_3x_client(u, proto)
    if client_id or flow or str(u.get("security", "")).lower() == "xtls":
        settings: Dict[str, Any] = {}
        if client_id:
            settings["id"] = str(client_id)
        if flow:
            settings["flow"] = flow
        proxies["vless"] = settings
    if u.get("method") or u.get("shadowsocks"):
        ss: Dict[str, Any] = {"method": u.get("method") or "chacha20-ietf-poly1305"}
        if password:
            ss["password"] = str(password)
        proxies["shadowsocks"] = ss
    if password and ("trojan" in str(u.get("protocol", "")).lower() or not proxies):
        proxies.setdefault("trojan", {"password": str(password)} if password else {})
    return proxies


def _extract_3x_identity(client: Dict[str, Any]) -> tuple[str, str]:
    """Return ``(sub_id, email)`` from a 3x-ui client row — unchanged from source."""
    sub_id = str(client.get("subId") or client.get("sub_id") or "").strip()
    email = str(client.get("email") or "").strip()
    return sub_id, email


def parse_upload(filename: str, content: bytes) -> List[Dict[str, Any]]:
    return parse_upload_with_meta(filename, content).rows


def is_panel_dump_upload(filename: str, content: bytes) -> bool:
    """True for 3x-ui SQLite / SQL dump / PostgreSQL pg_dump backups."""
    if not content:
        return False
    if content.startswith(_SQLITE_MAGIC) or content[:5] == _PGDMP_MAGIC:
        return True
    suffix = Path(filename or "").suffix.lower()
    return suffix in _DUMP_SUFFIXES


def parse_upload_with_meta(filename: str, content: bytes) -> ParseResult:
    name = (filename or "").lower()
    if is_panel_dump_upload(filename, content):
        return _parse_panel_dump(filename, content)

    text = content.decode("utf-8", errors="replace").strip()
    if not text:
        raise ValueError("Empty file")

    if name.endswith(".csv"):
        rows = _parse_csv(text)
        return ParseResult(rows=rows, source="csv", format_hint="csv")

    if name.endswith(".txt") or _looks_like_links(text):
        rows = _parse_links(text)
        return ParseResult(rows=rows, source="links", format_hint="links")

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Invalid JSON — for 3x-ui panel restore use a .dump / .db / .sql backup file"
        ) from exc

    return _parse_json(data, name)


def _parse_panel_dump(filename: str, content: bytes) -> ParseResult:
    """Load a 3x-ui panel backup and convert clients into import rows."""
    from app.migration.three_x_ui import _load_backup

    if not content:
        raise ValueError("Empty dump file")
    suffix = Path(filename or "panel.dump").suffix.lower() or ".dump"
    if suffix not in _DUMP_SUFFIXES:
        suffix = ".dump"
    tmp_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        backup = _load_backup(tmp_path)
    except FileNotFoundError as exc:
        raise ValueError(f"Dump file not found: {filename}") from exc
    except Exception as exc:
        raise ValueError(f"Cannot read panel dump: {exc}") from exc
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)

    if not isinstance(backup, dict):
        raise ValueError("Unsupported dump contents")

    raw_inbounds = backup.get("inbounds") or backup.get("obj") or []
    if isinstance(raw_inbounds, dict):
        inbounds = list(raw_inbounds.values())
    elif isinstance(raw_inbounds, list):
        inbounds = raw_inbounds
    else:
        inbounds = []
    if not inbounds:
        raise ValueError("Dump has no inbounds/clients to import")

    rows = _merge_rows_by_username(
        _parse_3xui_inbounds_bundle({"inbounds": inbounds})
    )
    if not rows:
        raise ValueError("Dump has no clients to import")
    return ParseResult(
        rows=rows,
        source="3x-ui-dump",
        format_hint=Path(filename or "").suffix.lower().lstrip(".") or "dump",
    )


def _merge_rows_by_username(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapse multi-inbound dump clients into one import row per username."""
    order: List[str] = []
    by_name: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        name = (row.get("username") or "").strip()
        if not name:
            continue
        if name not in by_name:
            by_name[name] = {
                **row,
                "proxies": {
                    k: dict(v) if isinstance(v, dict) else {}
                    for k, v in (row.get("proxies") or {}).items()
                },
                "inbounds": {
                    k: list(v) for k, v in (row.get("inbounds") or {}).items()
                },
                "sub_id": row.get("sub_id"),
                "email": row.get("email"),
                "used_traffic": int(row.get("used_traffic") or 0),
            }
            order.append(name)
            continue
        dest = by_name[name]
        if not dest.get("sub_id") and row.get("sub_id"):
            dest["sub_id"] = row.get("sub_id")
        if not dest.get("email") and row.get("email"):
            dest["email"] = row.get("email")
        # Shared 3x-ui meter is stamped on every inbound copy — take MAX, not SUM.
        try:
            dest["used_traffic"] = max(
                int(dest.get("used_traffic") or 0),
                int(row.get("used_traffic") or 0),
            )
        except (TypeError, ValueError):
            pass
        for proto, settings in (row.get("proxies") or {}).items():
            if not isinstance(settings, dict):
                continue
            cur = dest["proxies"].setdefault(proto, {})
            for key, value in settings.items():
                if value not in (None, "") and not cur.get(key):
                    cur[key] = value
        for proto, tags in (row.get("inbounds") or {}).items():
            dest["inbounds"].setdefault(proto, [])
            for tag in tags or []:
                if tag not in dest["inbounds"][proto]:
                    dest["inbounds"][proto].append(tag)
        try:
            if int(row.get("data_limit") or 0) > int(dest.get("data_limit") or 0):
                dest["data_limit"] = int(row.get("data_limit") or 0)
        except (TypeError, ValueError):
            pass
        try:
            if int(row.get("expire") or 0) > int(dest.get("expire") or 0):
                dest["expire"] = int(row.get("expire") or 0)
        except (TypeError, ValueError):
            pass
    return [by_name[name] for name in order]


def _looks_like_links(text: str) -> bool:
    for line in text.splitlines()[:20]:
        s = line.strip()
        if s.startswith(("vless://", "vmess://", "trojan://", "ss://", "ssr://")):
            return True
    return False


def _parse_json(data: Any, filename: str) -> ParseResult:
    warnings: List[str] = []

    if isinstance(data, list):
        if data and isinstance(data[0], str):
            rows = _parse_links("\n".join(data))
            return ParseResult(rows=rows, source="links", format_hint="json-links")
        if data and isinstance(data[0], dict) and _is_inbound_dict(data[0]):
            rows = _parse_inbound_list(data)
            return ParseResult(rows=rows, source="3x-ui", format_hint="inbounds-array")
        return ParseResult(
            rows=[_normalize_user(u, "marzban") for u in data if isinstance(u, dict)],
            source="marzban",
            format_hint="users-array",
        )

    if not isinstance(data, dict):
        raise ValueError("Unsupported JSON root type")

    if _looks_like_marzban_user(data):
        return ParseResult(
            rows=[_normalize_user(data, "marzban")],
            source="marzban",
            format_hint="single-user",
        )

    for key in ("users", "items", "objects", "clients_list"):
        if key in data and isinstance(data[key], list):
            src = "pasarguard" if key == "objects" else "marzban"
            rows = [_normalize_user(u, src) for u in data[key] if isinstance(u, dict)]
            return ParseResult(rows=rows, source=src, format_hint=key)

    if "clients" in data and isinstance(data["clients"], list):
        rows = _parse_3xui_clients(data["clients"], data)
        return ParseResult(rows=rows, source="3x-ui", format_hint="clients")

    if "inbounds" in data:
        inb = data["inbounds"]
        if isinstance(inb, list):
            rows = _parse_3xui_inbounds_bundle(data)
            return ParseResult(rows=rows, source="3x-ui", format_hint="inbounds-bundle")
        if isinstance(inb, dict):
            rows = _parse_3xui_inbounds_bundle({"inbounds": list(inb.values())})
            return ParseResult(rows=rows, source="3x-ui", format_hint="inbounds-map")

    if "obj" in data and isinstance(data["obj"], dict):
        return _parse_json(data["obj"], filename)

    if _is_inbound_dict(data):
        rows = _parse_inbound_list([data])
        return ParseResult(rows=rows, source="3x-ui", format_hint="single-inbound")

    if "data" in data and isinstance(data["data"], (list, dict)):
        inner = data["data"]
        if isinstance(inner, list):
            return _parse_json(inner, filename)
        return _parse_json(inner, filename)

    raise ValueError(
        "Unsupported JSON; use Marzban users export, 3x-ui inbound backup, CSV, or a .txt of share links"
    )


def _looks_like_marzban_user(d: Dict[str, Any]) -> bool:
    return bool(d.get("username")) and ("proxies" in d or "inbounds" in d or "data_limit" in d)


def _is_inbound_dict(d: Dict[str, Any]) -> bool:
    return bool(d.get("protocol")) and (
        "settings" in d or "clients" in d or "port" in d or "listen" in d
    )


def _parse_inbound_list(inbounds: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return _parse_3xui_inbounds_bundle({"inbounds": inbounds})


def _parse_csv(text: str) -> List[Dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text))
    rows: List[Dict[str, Any]] = []
    for row in reader:
        username = (row.get("username") or row.get("user") or row.get("email") or "").strip()
        username = _sanitize_username(username, "csv")
        if not username:
            continue
        protos_raw = row.get("protocols") or row.get("protocol") or "vless"
        protos = [PROTO_ALIASES.get(p.strip().lower(), p.strip().lower()) for p in str(protos_raw).split(",") if p.strip()]
        rows.append(
            {
                "username": username,
                "data_limit": _parse_limit_bytes(
                    row.get("limit_gb") or row.get("data_limit_gb") or row.get("total") or row.get("data_limit")
                ),
                "expire": _parse_expire(row.get("expire") or row.get("expiry") or row.get("expiryTime")),
                "note": (row.get("note") or row.get("comment") or "").strip(),
                "status": _map_status(row.get("status") or row.get("enable")),
                "proxies": {p: {} for p in protos if p},
                "inbounds": {},
                "conflict": None,
                "source": "csv",
            }
        )
    return rows


def _parse_3xui_clients(clients: List[Dict[str, Any]], root: Dict[str, Any]) -> List[Dict[str, Any]]:
    default_inbound = None
    default_proto = "vless"
    inbounds = root.get("inbounds") or []
    if inbounds and isinstance(inbounds[0], dict):
        default_inbound = inbounds[0].get("tag") or inbounds[0].get("remark")
        default_proto = PROTO_ALIASES.get(str(inbounds[0].get("protocol", "vless")).lower(), "vless")
    rows = []
    for c in clients:
        if not isinstance(c, dict):
            continue
        u = _normalize_user(c, source="3x-ui")
        u["proxies"] = _proxies_for_3x_client(c, default_proto)
        sub_id, email = _extract_3x_identity(c)
        if sub_id:
            u["sub_id"] = sub_id
        if email:
            u["email"] = email
        if default_inbound and not u["inbounds"]:
            u["inbounds"] = {default_proto: [str(default_inbound)]}
        rows.append(u)
    return rows


def _parse_3xui_inbounds_bundle(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen: set = set()
    for inbound in data.get("inbounds") or []:
        if not isinstance(inbound, dict):
            continue
        tag = str(inbound.get("tag") or inbound.get("remark") or inbound.get("listen") or "imported")
        proto = PROTO_ALIASES.get(str(inbound.get("protocol") or "vless").lower(), "vless")
        settings = inbound.get("settings") or {}
        if isinstance(settings, str):
            try:
                settings = json.loads(settings)
            except json.JSONDecodeError:
                settings = {}
        clients = settings.get("clients") or inbound.get("clients") or []
        if isinstance(clients, str):
            try:
                clients = json.loads(clients)
            except json.JSONDecodeError:
                clients = []
        for c in clients:
            if not isinstance(c, dict):
                continue
            u = _normalize_user(c, source="3x-ui")
            if not u["username"]:
                u["username"] = _sanitize_username(str(c.get("email") or c.get("id") or ""), "3x-ui")
            if not u["username"]:
                continue
            key = (u["username"], proto, tag)
            if key in seen:
                continue
            seen.add(key)
            u["inbounds"].setdefault(proto, [])
            if tag not in u["inbounds"][proto]:
                u["inbounds"][proto].append(tag)
            # Prefer this inbound's protocol credentials (keep original UUID/password).
            proto_proxy = _proxies_for_3x_client(c, proto)
            for p_name, p_settings in proto_proxy.items():
                existing = u["proxies"].get(p_name) or {}
                merged = dict(existing)
                merged.update({k: v for k, v in (p_settings or {}).items() if v not in (None, "")})
                u["proxies"][p_name] = merged
            sub_id, email = _extract_3x_identity(c)
            if sub_id:
                u["sub_id"] = sub_id
            if email:
                u["email"] = email
            rows.append(u)
    return rows


def _parse_links(text: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen_names: set = set()
    idx = 0
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parsed = _parse_one_link(line)
        if not parsed:
            continue
        username, proto, settings = parsed
        if username in seen_names:
            idx += 1
            username = _sanitize_username(f"{username}_{idx}", "links")
        if not username:
            idx += 1
            username = _sanitize_username(f"import_{idx}", "links")
        seen_names.add(username)
        rows.append(
            {
                "username": username,
                "data_limit": 0,
                "expire": 0,
                "note": "imported from link",
                "status": "active",
                "proxies": {proto: settings},
                "inbounds": {},
                "conflict": None,
                "source": "links",
            }
        )
    return rows


def _parse_one_link(line: str) -> Optional[Tuple[str, str, Dict[str, Any]]]:
    if line.startswith("vmess://"):
        return _parse_vmess_link(line)
    parsed = urlparse(line)
    scheme = (parsed.scheme or "").lower()
    if scheme not in PROTO_ALIASES:
        return None
    proto = PROTO_ALIASES[scheme]
    user = unquote(parsed.username or "")
    params = parse_qs(parsed.query)
    settings: Dict[str, Any] = {}
    if proto == "vless":
        flow = (params.get("flow") or [""])[0]
        if flow:
            settings["flow"] = flow
        name = unquote(parsed.fragment or user)
        username = _sanitize_username(name.split("@")[0] if "@" in name else name, "links")
        if not username:
            username = _sanitize_username(user[:12] if user else "vless_user", "links")
        return username, proto, settings
    if proto == "trojan":
        name = unquote(parsed.fragment or user)
        username = _sanitize_username(name or user[:12], "links")
        return username or _sanitize_username("trojan_user", "links"), proto, settings
    if proto == "shadowsocks":
        name = unquote(parsed.fragment or "")
        username = _sanitize_username(name or user[:12], "links")
        method = (params.get("method") or [""])[0]
        if method:
            settings["method"] = method
        return username or _sanitize_username("ss_user", "links"), proto, settings
    return None


def _parse_vmess_link(line: str) -> Optional[Tuple[str, str, Dict[str, Any]]]:
    try:
        raw = line[8:]
        pad = "=" * (-len(raw) % 4)
        obj = json.loads(base64.b64decode(raw + pad).decode("utf-8", errors="replace"))
    except Exception:
        return None
    name = str(obj.get("ps") or obj.get("remark") or obj.get("id") or "")
    username = _sanitize_username(name, "links") or _sanitize_username(str(obj.get("id", ""))[:12], "links")
    if not username:
        return None
    return username, "vmess", {}


def apply_inbound_mapping(
    rows: List[Dict[str, Any]],
    mapping: Dict[str, str],
    known_tags: set,
) -> List[Dict[str, Any]]:
    out = []
    for row in rows:
        r = dict(row)
        inb = _normalize_inbounds(r.get("inbounds") or {})
        new_inb: Dict[str, List[str]] = {}
        for proto, tags in inb.items():
            mapped = []
            for tag in tags:
                target = mapping.get(tag, tag)
                if target and target in known_tags:
                    mapped.append(target)
            if mapped:
                new_inb[proto] = mapped
        r["inbounds"] = new_inb
        out.append(r)
    return out


def annotate_conflicts(rows: List[Dict[str, Any]], existing: set) -> List[Dict[str, Any]]:
    out = []
    batch_seen: set = set()
    for row in rows:
        r = dict(row)
        name = r.get("username") or ""
        if not name:
            r["conflict"] = "invalid_username"
        elif name in existing:
            r["conflict"] = "exists"
        elif name in batch_seen:
            r["conflict"] = "duplicate_in_file"
        else:
            r["conflict"] = None
            batch_seen.add(name)
        out.append(r)
    return out


def count_by_conflict(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    total = len(rows)
    exists = sum(1 for r in rows if r.get("conflict") == "exists")
    invalid = sum(1 for r in rows if r.get("conflict") in ("invalid_username", "duplicate_in_file"))
    new = total - exists - invalid
    return {"total": total, "new": new, "exists": exists, "invalid": invalid}
