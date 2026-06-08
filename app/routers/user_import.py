"""Bulk user import from Marzban, 3x-ui, PasarGuard, CSV, and share-link files."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app import logger, xray
from app.db import Session, crud, get_db
from app.models.admin import Admin
from app.models.proxy import ProxySettings, ProxyTypes
from app.models.user import UserCreate, UserModify, UserStatusCreate, UserStatusModify
from app.rbac import require_permission
from app.user_import import parsers
from app.utils import responses

router = APIRouter(
    tags=["User Import"],
    prefix="/api",
    responses={401: responses._401, 403: responses._403},
)

PREVIEW_ROW_LIMIT = 2000
MAX_FILE_BYTES = 10 * 1024 * 1024


class ImportRow(BaseModel):
    username: str
    data_limit: int = 0
    expire: int = 0
    note: str = ""
    status: str = "active"
    proxies: Dict[str, Any] = {}
    inbounds: Dict[str, List[str]] = {}
    conflict: Optional[str] = None
    unmapped_inbounds: List[str] = []
    source: Optional[str] = None


class ImportCounts(BaseModel):
    total: int = 0
    new: int = 0
    exists: int = 0
    invalid: int = 0


class ImportPreviewResponse(BaseModel):
    rows: List[ImportRow]
    total: int
    truncated: bool = False
    source: str = "unknown"
    format_hint: str = ""
    counts: ImportCounts
    panel_inbound_tags: List[str] = []


class ImportApplyBody(BaseModel):
    rows: List[ImportRow]
    skip_existing: bool = True
    inbound_mapping: Dict[str, str] = {}


class ImportApplyResult(BaseModel):
    created: int
    skipped: int
    errors: List[str]
    source: Optional[str] = None


def _known_inbound_tags() -> set:
    return set(xray.config.inbounds_by_tag.keys())


def _map_row(row: dict, known_tags: set) -> ImportRow:
    unmapped: List[str] = []
    inbounds = row.get("inbounds") or {}
    if isinstance(inbounds, dict):
        for proto, tags in inbounds.items():
            if not isinstance(tags, list):
                continue
            for tag in tags:
                if tag and tag not in known_tags:
                    unmapped.append(tag)
    return ImportRow(
        username=row.get("username") or "",
        data_limit=int(row.get("data_limit") or 0),
        expire=int(row.get("expire") or 0),
        note=row.get("note") or "",
        status=row.get("status") or "active",
        proxies=row.get("proxies") or {},
        inbounds=inbounds if isinstance(inbounds, dict) else {},
        conflict=row.get("conflict"),
        unmapped_inbounds=sorted(set(unmapped)),
        source=row.get("source"),
    )


async def _read_and_parse(file: UploadFile) -> tuple[list, parsers.ParseResult]:
    content = await file.read()
    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(status_code=400, detail=f"File too large (max {MAX_FILE_BYTES // 1024 // 1024}MB)")
    try:
        result = parsers.parse_upload_with_meta(file.filename or "upload.json", content)
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.rows, result


def _prepare_rows(
    parsed: List[dict],
    db: Session,
    admin: Admin,
    inbound_mapping: Dict[str, str],
) -> List[ImportRow]:
    users = crud.get_users(db, offset=0, limit=100000, admin=admin)
    existing = {u.username for u in users}
    annotated = parsers.annotate_conflicts(parsed, existing)
    known = _known_inbound_tags()
    if inbound_mapping:
        annotated = parsers.apply_inbound_mapping(annotated, inbound_mapping, known)
    return [_map_row(r, known) for r in annotated]


@router.post("/users/import/preview", response_model=ImportPreviewResponse)
async def import_preview(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:write")),
):
    parsed, meta = await _read_and_parse(file)
    mapped = _prepare_rows(parsed, db, admin, {})
    counts = parsers.count_by_conflict([r.model_dump() for r in mapped])
    truncated = len(mapped) > PREVIEW_ROW_LIMIT
    return ImportPreviewResponse(
        rows=mapped[:PREVIEW_ROW_LIMIT],
        total=len(mapped),
        truncated=truncated,
        source=meta.source,
        format_hint=meta.format_hint,
        counts=ImportCounts(**counts),
        panel_inbound_tags=sorted(_known_inbound_tags()),
    )


@router.get("/users/import/inbounds")
def import_inbound_tags(_: Admin = Depends(require_permission("users:read"))):
    return {"tags": sorted(_known_inbound_tags())}


@router.get("/users/import/formats")
def import_formats(_: Admin = Depends(require_permission("users:read"))):
    return {
        "formats": [
            {"id": "marzban", "extensions": [".json"], "hint_key": "users.importFmtMarzban"},
            {"id": "3x-ui", "extensions": [".json"], "hint_key": "users.importFmt3xui"},
            {"id": "csv", "extensions": [".csv"], "hint_key": "users.importFmtCsv"},
            {"id": "links", "extensions": [".txt", ".json"], "hint_key": "users.importFmtLinks"},
        ]
    }


def _row_to_user_create(row: ImportRow) -> UserCreate:
    proxies_raw = row.proxies or {}
    if not proxies_raw:
        for pt, ins in xray.config.inbounds_by_protocol.items():
            if ins:
                proxies_raw = {pt.value: {}}
                break
    proxies: Dict[ProxyTypes, ProxySettings] = {}
    for key, settings in proxies_raw.items():
        try:
            pt = ProxyTypes(key)
        except ValueError:
            continue
        proxies[pt] = ProxySettings.from_dict(pt, settings if isinstance(settings, dict) else {})

    if not proxies:
        raise ValueError("No valid protocols in row")

    inbounds: Dict[ProxyTypes, List[str]] = {}
    for key, tags in (row.inbounds or {}).items():
        try:
            pt = ProxyTypes(key)
        except ValueError:
            continue
        inbounds[pt] = [t for t in tags if t in xray.config.inbounds_by_tag]
    if not inbounds:
        for pt in proxies:
            ins = xray.config.inbounds_by_protocol.get(pt) or []
            inbounds[pt] = [i.tag for i in ins]

    status = UserStatusCreate.active
    if row.status.lower() == "on_hold":
        status = UserStatusCreate.on_hold

    return UserCreate(
        username=row.username,
        proxies=proxies,
        inbounds=inbounds,
        data_limit=row.data_limit or None,
        expire=row.expire or None,
        note=row.note or "",
        status=status,
    )


def _import_rows(
    rows: List[ImportRow],
    skip_existing: bool,
    db: Session,
    admin: Admin,
    bg: BackgroundTasks,
) -> ImportApplyResult:
    created = skipped = 0
    errors: List[str] = []
    dbadmin = crud.get_admin(db, admin.username)

    for row in rows:
        if row.conflict in ("exists", "duplicate_in_file"):
            if skip_existing:
                skipped += 1
                continue
            errors.append(f"{row.username}: {row.conflict}")
            continue
        if row.conflict == "invalid_username" or not row.username:
            errors.append(f"{row.username or '?'}: invalid username")
            continue
        if crud.get_user(db, row.username):
            if skip_existing:
                skipped += 1
                continue
            errors.append(f"{row.username}: already exists")
            continue
        try:
            new_user = _row_to_user_create(row)
            for proxy_type in new_user.proxies:
                if proxy_type not in (
                    ProxyTypes.WireGuard,
                    ProxyTypes.Hysteria2,
                    ProxyTypes.TUIC,
                ) and not xray.config.inbounds_by_protocol.get(proxy_type):
                    raise ValueError(f"Protocol {proxy_type} is disabled")
            dbuser = crud.create_user(db, new_user, admin=dbadmin)
            if row.status.lower() == "disabled":
                crud.update_user(db, dbuser, UserModify(status=UserStatusModify.disabled))
            bg.add_task(xray.operations.add_user, dbuser=dbuser)
            created += 1
        except Exception as exc:
            errors.append(f"{row.username}: {exc}")

    if created:
        logger.info("Imported %s users", created)
    return ImportApplyResult(created=created, skipped=skipped, errors=errors)


@router.post("/users/import/apply", response_model=ImportApplyResult)
def import_apply(
    body: ImportApplyBody,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:write")),
):
    known = _known_inbound_tags()
    rows = body.rows
    if body.inbound_mapping:
        raw = [r.model_dump() for r in body.rows]
        fixed = parsers.apply_inbound_mapping(raw, body.inbound_mapping, known)
        rows = [_map_row(r, known) for r in fixed]
    result = _import_rows(rows, body.skip_existing, db, admin, bg)
    return result


@router.post("/users/import/apply-file", response_model=ImportApplyResult)
async def import_apply_file(
    bg: BackgroundTasks,
    file: UploadFile = File(...),
    skip_existing: bool = Form(True),
    inbound_mapping: str = Form("{}"),
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:write")),
):
    """Import entire file server-side (recommended for large exports)."""
    parsed, meta = await _read_and_parse(file)
    try:
        mapping = json.loads(inbound_mapping or "{}")
        if not isinstance(mapping, dict):
            mapping = {}
    except json.JSONDecodeError:
        mapping = {}
    rows = _prepare_rows(parsed, db, admin, mapping)
    importable = [r for r in rows if r.conflict not in ("invalid_username",)]
    result = _import_rows(importable, skip_existing, db, admin, bg)
    result.source = meta.source
    return result
