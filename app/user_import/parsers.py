"""Parse Marzban-style JSON, 3x-ui exports, and generic CSV."""
from __future__ import annotations

import csv
import io
import json
import re
from typing import Any, Dict, List, Optional


def _parse_expire(raw: Any) -> int:
    if raw is None or raw == "" or raw == 0:
        return 0
    try:
        v = int(raw)
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


def _normalize_proxies(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return {str(k): (v if isinstance(v, dict) else {}) for k, v in raw.items()}
    return {}


def _normalize_inbounds(raw: Any) -> Dict[str, List[str]]:
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, List[str]] = {}
    for key, tags in raw.items():
        if isinstance(tags, list):
            out[str(key)] = [str(t) for t in tags if t]
        elif isinstance(tags, str) and tags:
            out[str(key)] = [tags]
    return out


def parse_upload(filename: str, content: bytes) -> List[Dict[str, Any]]:
    name = (filename or "").lower()
    text = content.decode("utf-8", errors="replace")

    if name.endswith(".csv"):
        return _parse_csv(text)

    data = json.loads(text)
    if isinstance(data, list):
        return [_normalize_user(u, source="marzban") for u in data]
    if isinstance(data, dict):
        if "users" in data and isinstance(data["users"], list):
            return [_normalize_user(u, source="marzban") for u in data["users"]]
        if "items" in data and isinstance(data["items"], list):
            return [_normalize_user(u, source="marzban") for u in data["items"]]
        if "clients" in data and isinstance(data["clients"], list):
            return _parse_3xui_clients(data["clients"], data)
        if "inbounds" in data and isinstance(data["inbounds"], list):
            return _parse_3xui_inbounds_bundle(data)
    raise ValueError("Unsupported JSON shape; expected users[], clients[], or 3x-ui inbounds")


def _parse_csv(text: str) -> List[Dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text))
    rows: List[Dict[str, Any]] = []
    for row in reader:
        username = (row.get("username") or row.get("user") or row.get("email") or "").strip()
        if not username:
            continue
        protos_raw = row.get("protocols") or row.get("protocol") or "vless"
        protos = [p.strip() for p in str(protos_raw).split(",") if p.strip()]
        rows.append(
            {
                "username": username,
                "data_limit": _parse_limit_bytes(row.get("limit_gb") or row.get("data_limit_gb") or row.get("total")),
                "expire": _parse_expire(row.get("expire") or row.get("expiry") or row.get("expiryTime")),
                "note": (row.get("note") or row.get("comment") or "").strip(),
                "status": _map_status(row.get("status") or row.get("enable")),
                "proxies": {p: {} for p in protos},
                "inbounds": {},
                "conflict": None,
                "source": "csv",
            }
        )
    return rows


def _map_status(raw: Any) -> str:
    if raw is None:
        return "active"
    if isinstance(raw, bool):
        return "active" if raw else "disabled"
    s = str(raw).strip().lower()
    if s in ("0", "false", "disabled", "off"):
        return "disabled"
    if s in ("on_hold", "on hold"):
        return "on_hold"
    return "active"


def _normalize_user(u: Dict[str, Any], source: str = "marzban") -> Dict[str, Any]:
    username = (u.get("username") or u.get("email") or "").strip()
    if "@" in username and source == "3x-ui":
        username = username.split("@", 1)[0]
    username = re.sub(r"[^a-zA-Z0-9-_@.]", "_", username)[:32]
    return {
        "username": username,
        "data_limit": _parse_limit_bytes(u.get("data_limit") or u.get("totalGB") or u.get("total")),
        "expire": _parse_expire(u.get("expire") or u.get("expiryTime") or u.get("expiry")),
        "note": (u.get("note") or u.get("comment") or "").strip(),
        "status": _map_status(u.get("status") if "status" in u else u.get("enable")),
        "proxies": _normalize_proxies(u.get("proxies") or _infer_proxies_from_3x(u)),
        "inbounds": _normalize_inbounds(u.get("inbounds") or {}),
        "conflict": None,
        "source": source,
    }


def _infer_proxies_from_3x(u: Dict[str, Any]) -> Dict[str, Any]:
    """Guess protocols from 3x-ui client fields."""
    proxies: Dict[str, Any] = {}
    if u.get("flow") or u.get("vless"):
        proxies["vless"] = {"flow": u.get("flow") or ""}
    if u.get("method") or u.get("shadowsocks"):
        proxies["shadowsocks"] = {"method": u.get("method") or "chacha20-ietf-poly1305"}
    if u.get("password") and not proxies:
        proxies["trojan"] = {}
    if not proxies:
        protos = u.get("protocol") or u.get("type")
        if protos:
            proxies[str(protos)] = {}
    return proxies


def _parse_3xui_clients(clients: List[Dict[str, Any]], root: Dict[str, Any]) -> List[Dict[str, Any]]:
    default_inbound = None
    inbounds = root.get("inbounds") or []
    if inbounds and isinstance(inbounds[0], dict):
        default_inbound = inbounds[0].get("tag") or inbounds[0].get("remark")
    rows = []
    for c in clients:
        u = _normalize_user(c, source="3x-ui")
        if default_inbound and not u["inbounds"]:
            proto = next(iter(u["proxies"].keys()), "vless")
            if not u["proxies"]:
                u["proxies"] = {proto: {}}
            u["inbounds"] = {proto: [default_inbound]}
        rows.append(u)
    return rows


def _parse_3xui_inbounds_bundle(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """3x-ui settings export with inbounds[].settings.clients[]"""
    rows: List[Dict[str, Any]] = []
    for inbound in data.get("inbounds") or []:
        if not isinstance(inbound, dict):
            continue
        tag = inbound.get("tag") or inbound.get("remark") or "imported"
        proto = (inbound.get("protocol") or "vless").lower()
        settings = inbound.get("settings") or {}
        clients = settings.get("clients") or []
        for c in clients:
            if not isinstance(c, dict):
                continue
            u = _normalize_user(c, source="3x-ui")
            if not u["username"]:
                u["username"] = (c.get("email") or c.get("id") or "").strip()[:32]
            if u["username"]:
                u["inbounds"].setdefault(proto, [])
                if tag not in u["inbounds"][proto]:
                    u["inbounds"][proto].append(tag)
                if not u["proxies"]:
                    u["proxies"] = {proto: {}}
                rows.append(u)
    return rows


def apply_inbound_mapping(
    rows: List[Dict[str, Any]],
    mapping: Dict[str, str],
    known_tags: set,
) -> List[Dict[str, Any]]:
    """Rewrite inbound tags using operator-provided mapping."""
    out = []
    for row in rows:
        r = dict(row)
        inb = _normalize_inbounds(r.get("inbounds") or {})
        new_inb: Dict[str, List[str]] = {}
        for proto, tags in inb.items():
            mapped = []
            for tag in tags:
                target = mapping.get(tag, tag)
                if target in known_tags:
                    mapped.append(target)
            if mapped:
                new_inb[proto] = mapped
        r["inbounds"] = new_inb
        out.append(r)
    return out


def annotate_conflicts(rows: List[Dict[str, Any]], existing: set) -> List[Dict[str, Any]]:
    out = []
    for row in rows:
        r = dict(row)
        if not r.get("username"):
            r["conflict"] = "invalid_username"
        elif r["username"] in existing:
            r["conflict"] = "exists"
        else:
            r["conflict"] = None
        out.append(r)
    return out
