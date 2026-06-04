"""Bulk user import from Marzban JSON or CSV."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from app import logger, xray
from app.db import Session, crud, get_db
from app.models.admin import Admin
from app.models.proxy import ProxySettings, ProxyTypes
from app.models.user import UserCreate, UserStatusCreate
from app.rbac import require_permission
from app.user_import import parsers
from app.utils import responses

router = APIRouter(
    tags=["User Import"],
    prefix="/api",
    responses={401: responses._401, 403: responses._403},
)


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


class ImportPreviewResponse(BaseModel):
    rows: List[ImportRow]
    total: int
    panel_inbound_tags: List[str] = []


class ImportApplyBody(BaseModel):
    rows: List[ImportRow]
    skip_existing: bool = True
    inbound_mapping: Dict[str, str] = {}


class ImportApplyResult(BaseModel):
    created: int
    skipped: int
    errors: List[str]


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
    )


@router.post("/users/import/preview", response_model=ImportPreviewResponse)
async def import_preview(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:write")),
):
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 5MB)")
    try:
        parsed = parsers.parse_upload(file.filename or "upload.json", content)
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    users = crud.get_users(db, offset=0, limit=100000, admin=admin)
    existing = {u.username for u in users}
    annotated = parsers.annotate_conflicts(parsed, existing)
    known = _known_inbound_tags()
    rows = [_map_row(r, known) for r in annotated[:500]]
    return ImportPreviewResponse(
        rows=rows,
        total=len(annotated),
        panel_inbound_tags=sorted(known),
    )


@router.get("/users/import/inbounds")
def import_inbound_tags(_: Admin = Depends(require_permission("users:read"))):
    return {"tags": sorted(_known_inbound_tags())}


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


@router.post("/users/import/apply", response_model=ImportApplyResult)
def import_apply(
    body: ImportApplyBody,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: Admin = Depends(require_permission("users:write")),
):
    created = skipped = 0
    errors: List[str] = []
    dbadmin = crud.get_admin(db, admin.username)

    known = _known_inbound_tags()
    mapped_rows = body.rows
    if body.inbound_mapping:
        raw = [r.model_dump() for r in body.rows]
        fixed = parsers.apply_inbound_mapping(raw, body.inbound_mapping, known)
        mapped_rows = [_map_row(r, known) for r in fixed]

    for row in mapped_rows:
        if row.conflict == "exists":
            if body.skip_existing:
                skipped += 1
                continue
            errors.append(f"{row.username}: already exists")
            continue
        if row.conflict == "invalid_username" or not row.username:
            errors.append(f"{row.username or '?'}: invalid username")
            continue
        if crud.get_user(db, row.username):
            if body.skip_existing:
                skipped += 1
                continue
            errors.append(f"{row.username}: already exists")
            continue
        try:
            new_user = _row_to_user_create(row)
            for proxy_type in new_user.proxies:
                if proxy_type != ProxyTypes.WireGuard and not xray.config.inbounds_by_protocol.get(proxy_type):
                    raise ValueError(f"Protocol {proxy_type} is disabled")
            dbuser = crud.create_user(db, new_user, admin=dbadmin)
            bg.add_task(xray.operations.add_user, dbuser=dbuser)
            created += 1
        except Exception as exc:
            errors.append(f"{row.username}: {exc}")

    if created:
        logger.info("Imported %s users", created)
    return ImportApplyResult(created=created, skipped=skipped, errors=errors)
