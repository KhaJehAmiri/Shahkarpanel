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
MAX_DUMP_BYTES = 100 * 1024 * 1024


class ImportRow(BaseModel):
    username: str
    data_limit: int = 0
    used_traffic: int = 0
    expire: int = 0
    note: str = ""
    status: str = "active"
    proxies: Dict[str, Any] = {}
    inbounds: Dict[str, List[str]] = {}
    conflict: Optional[str] = None
    unmapped_inbounds: List[str] = []
    source: Optional[str] = None
    # Original 3x-ui subscription token / account label — must stay unchanged.
    sub_id: Optional[str] = None
    email: Optional[str] = None


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
        used_traffic=int(row.get("used_traffic") or 0),
        expire=int(row.get("expire") or 0),
        note=row.get("note") or "",
        status=row.get("status") or "active",
        proxies=row.get("proxies") or {},
        inbounds=inbounds if isinstance(inbounds, dict) else {},
        conflict=row.get("conflict"),
        unmapped_inbounds=sorted(set(unmapped)),
        source=row.get("source"),
        sub_id=(str(row.get("sub_id") or "").strip() or None),
        email=(str(row.get("email") or "").strip() or None),
    )


def _alias_endpoint_id_for_admin(db: Session, dbadmin) -> Optional[int]:
    """Prefer reseller branding subscription endpoint for preserved subId tokens."""
    if dbadmin is not None:
        try:
            from app.tenant import branding_scope_admin_id
            from app.tenant.subscription_domain import get_reseller_subscription_endpoint

            brand_ep = get_reseller_subscription_endpoint(
                db,
                getattr(dbadmin, "tenant_id", None),
                admin_id=branding_scope_admin_id(db, dbadmin),
            )
            if brand_ep is not None:
                return int(brand_ep.id)
        except Exception:
            pass
    default = crud.get_default_subscription_endpoint(db)
    return int(default.id) if default is not None else None


def _bind_sub_id_alias(
    db: Session,
    *,
    user_id: int,
    sub_id: Optional[str],
    endpoint_id: Optional[int],
) -> bool:
    """Attach original 3x-ui ``subId`` so old subscription URLs keep working."""
    token = (sub_id or "").strip()
    if not token or endpoint_id is None:
        return False
    crud.upsert_subscription_token_alias(
        db,
        token=token,
        user_id=user_id,
        endpoint_id=endpoint_id,
        source="3x-ui-import",
        commit=False,
    )
    return True


def _apply_usage_and_quota(dbuser, row: ImportRow) -> bool:
    """Restore used traffic + data limit/expiry from the dump onto a DB user."""
    changed = False
    used = int(row.used_traffic or 0)
    if used > 0 and int(getattr(dbuser, "used_traffic", 0) or 0) != used:
        dbuser.used_traffic = used
        # Keep split counters coherent when the dump only has a combined meter.
        if hasattr(dbuser, "used_traffic_up") and hasattr(dbuser, "used_traffic_down"):
            if not (dbuser.used_traffic_up or dbuser.used_traffic_down):
                dbuser.used_traffic_down = used
        changed = True
    if row.data_limit and int(getattr(dbuser, "data_limit", 0) or 0) != int(row.data_limit):
        dbuser.data_limit = int(row.data_limit)
        changed = True
    if row.expire and int(getattr(dbuser, "expire", 0) or 0) != int(row.expire):
        dbuser.expire = int(row.expire)
        changed = True
    return changed


def _repair_existing_from_dump(
    db: Session,
    dbuser,
    row: ImportRow,
    *,
    inbound_cache: dict,
    alias_endpoint_id: Optional[int],
) -> tuple[bool, bool]:
    """Restore original UUID/password + subId + traffic on an already-imported user."""
    repaired = False
    proxies_patch: Dict[str, Any] = {}
    for proto, settings in (row.proxies or {}).items():
        if not isinstance(settings, dict):
            continue
        if settings.get("id") or settings.get("password") or settings.get("uuid"):
            proxies_patch[proto] = settings
    if proxies_patch:
        try:
            crud.update_user(
                db,
                dbuser,
                UserModify(proxies=proxies_patch),
                commit=False,
                inbound_cache=inbound_cache,
            )
            repaired = True
        except Exception:
            repaired = False
    if _apply_usage_and_quota(dbuser, row):
        repaired = True
    aliased = _bind_sub_id_alias(
        db,
        user_id=dbuser.id,
        sub_id=row.sub_id,
        endpoint_id=alias_endpoint_id,
    )
    return repaired, aliased


def _max_upload_bytes(filename: str, content: bytes) -> int:
    if parsers.is_panel_dump_upload(filename, content):
        return MAX_DUMP_BYTES
    return MAX_FILE_BYTES


async def _read_and_parse(file: UploadFile) -> tuple[list, parsers.ParseResult]:
    content = await file.read()
    name = file.filename or "upload.json"
    limit = _max_upload_bytes(name, content)
    if len(content) > limit:
        raise HTTPException(
            status_code=400,
            detail=f"File too large (max {limit // 1024 // 1024}MB)",
        )
    try:
        result = parsers.parse_upload_with_meta(name, content)
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.rows, result


def _prepare_rows(
    parsed: List[dict],
    db: Session,
    admin: Admin,
    inbound_mapping: Dict[str, str],
) -> List[ImportRow]:
    # Usernames are globally unique. Query usernames directly — do not pass the
    # JWT/Pydantic Admin into ``User.admin == admin`` (needs a mapped ORM row).
    from app.db.models import User as DBUser

    existing = {name for (name,) in db.query(DBUser.username).all()}
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
            {
                "id": "3x-ui-dump",
                "extensions": [".dump", ".db", ".sql", ".sqlite", ".sqlite3"],
                "hint_key": "users.importFmt3xuiDump",
            },
            {"id": "csv", "extensions": [".csv"], "hint_key": "users.importFmtCsv"},
            {"id": "links", "extensions": [".txt", ".json"], "hint_key": "users.importFmtLinks"},
        ]
    }


def _default_inbounds_for_proxy(
    pt: ProxyTypes,
    proxy_settings: ProxySettings,
) -> List[str]:
    """Pick compatible panel inbound tags when dump tags are missing/unmapped."""
    from app.xray.inbound_match import inbound_matches_proxy

    if pt in (ProxyTypes.WireGuard, ProxyTypes.Hysteria2, ProxyTypes.TUIC, ProxyTypes.AnyTLS):
        return []
    ins = xray.config.inbounds_by_protocol.get(pt.value) or []
    tags = [
        i["tag"]
        for i in ins
        if inbound_matches_proxy(pt, i["tag"], proxy_settings, inbound_meta=i)
    ]
    if tags:
        return tags
    # Last resort: any inbound of this protocol (avoids empty-inbounds UserCreate error).
    return [i["tag"] for i in ins if i.get("tag")]


def _optional_empty_inbound_protocols() -> set:
    return {
        ProxyTypes.WireGuard,
        ProxyTypes.Hysteria2,
        ProxyTypes.TUIC,
        ProxyTypes.AnyTLS,
    }


def _first_panel_proxy_type() -> Optional[ProxyTypes]:
    """First protocol on this panel that requires inbound tags (usually vless)."""
    skip = _optional_empty_inbound_protocols()
    for key, ins in (xray.config.inbounds_by_protocol or {}).items():
        if not ins:
            continue
        try:
            pt = key if isinstance(key, ProxyTypes) else ProxyTypes(str(key))
        except ValueError:
            continue
        if pt in skip:
            continue
        return pt
    return None


def _credential_settings_for_proxy(
    target: ProxyTypes,
    proxies_raw: Dict[str, Any],
) -> Dict[str, Any]:
    """Reuse dump UUID/password when remapping trojan-only clients onto vless."""
    settings: Dict[str, Any] = {}
    for conf in (proxies_raw or {}).values():
        if not isinstance(conf, dict):
            continue
        for key in ("id", "uuid", "password"):
            val = conf.get(key)
            if not val:
                continue
            if target == ProxyTypes.VLESS:
                settings.setdefault("id", str(val))
            elif target == ProxyTypes.Trojan:
                settings.setdefault("password", str(val))
            elif target == ProxyTypes.Shadowsocks:
                settings.setdefault("password", str(val))
            else:
                settings.setdefault(key, val)
    return settings


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

    from app.xray.inbound_match import filter_inbound_tags

    inbounds: Dict[ProxyTypes, List[str]] = {}
    for key, tags in (row.inbounds or {}).items():
        try:
            pt = ProxyTypes(key)
        except ValueError:
            continue
        if pt not in proxies:
            continue
        proxy_settings = proxies[pt]
        known = [t for t in tags if t in xray.config.inbounds_by_tag]
        inbounds[pt] = filter_inbound_tags(pt, known, proxy_settings)

    # Dump tags often don't exist on this panel (or were left unmapped). Empty
    # ``{vless: []}`` still counts as "set" for UserCreate validation — fill
    # every protocol that has no usable tags from the live panel inbounds.
    optional = _optional_empty_inbound_protocols()
    for pt, proxy_settings in list(proxies.items()):
        if inbounds.get(pt):
            continue
        inbounds[pt] = _default_inbounds_for_proxy(pt, proxy_settings)

    # Drop protocols this panel cannot host (common: dump has trojan, panel is vless-only).
    for pt in list(proxies.keys()):
        if pt in optional:
            continue
        if not inbounds.get(pt):
            proxies.pop(pt, None)
            inbounds.pop(pt, None)

    if not proxies:
        target = _first_panel_proxy_type()
        if target is None:
            raise ValueError(
                f"No inbound on this panel to attach imported user «{row.username}»"
            )
        creds = _credential_settings_for_proxy(target, proxies_raw)
        proxies = {target: ProxySettings.from_dict(target, creds)}
        inbounds = {target: _default_inbounds_for_proxy(target, proxies[target])}
        if not inbounds[target]:
            raise ValueError(
                f"No {target.value} inbound on this panel to attach imported user "
                f"«{row.username}»"
            )

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
    """Bulk-import users with one inbound cache and batched commits.

    Per-row ``commit`` + ``get_user`` + ``add_user`` made large dump restores
    take minutes; this mirrors the master 3x-ui migration path instead.
    """
    import time

    from app.db.models import ProxyInbound, User as DBUser

    t0 = time.perf_counter()
    created = skipped = aliases = repaired = 0
    errors: List[str] = []
    dbadmin = crud.get_admin(db, admin.username)

    existing_ids = {
        name: uid for name, uid in db.query(DBUser.username, DBUser.id).all()
    }
    existing = set(existing_ids)
    inbound_cache = {row.tag: row for row in db.query(ProxyInbound).all()}
    alias_endpoint_id = _alias_endpoint_id_for_admin(db, dbadmin)

    # Cap by reseller max_users once (create_user would re-count every row).
    remaining_slots: Optional[int] = None
    if dbadmin is not None and dbadmin.max_users is not None:
        remaining_slots = max(
            0, int(dbadmin.max_users) - int(crud.get_users_count(db, admin=dbadmin))
        )

    COMMIT_EVERY = 100
    pending = 0

    for row in rows:
        if row.conflict == "invalid_username" or not row.username:
            errors.append(f"{row.username or '?'}: invalid username")
            continue

        already_here = row.username in existing or row.conflict in (
            "exists",
            "duplicate_in_file",
        )
        if already_here:
            if skip_existing or row.conflict == "duplicate_in_file":
                skipped += 1
                uid = existing_ids.get(row.username)
                if uid and (row.sub_id or row.proxies):
                    try:
                        with db.begin_nested():
                            dbuser = db.query(DBUser).filter(DBUser.id == uid).first()
                            if dbuser is not None:
                                was_repaired, aliased = _repair_existing_from_dump(
                                    db,
                                    dbuser,
                                    row,
                                    inbound_cache=inbound_cache,
                                    alias_endpoint_id=alias_endpoint_id,
                                )
                                if aliased:
                                    aliases += 1
                                if was_repaired:
                                    repaired += 1
                                if was_repaired or aliased:
                                    pending += 1
                    except Exception as exc:
                        errors.append(f"{row.username}: restore {exc}")
                continue
            errors.append(
                f"{row.username}: {row.conflict or 'already exists'}"
            )
            continue
        if remaining_slots is not None and remaining_slots <= 0:
            errors.append(f"{row.username}: reseller user limit reached")
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
            # SAVEPOINT: one bad row must not abort the whole batch.
            with db.begin_nested():
                dbuser = crud.create_user(
                    db,
                    new_user,
                    admin=dbadmin,
                    commit=False,
                    inbound_cache=inbound_cache,
                )
                if row.status.lower() == "disabled":
                    crud.update_user(
                        db,
                        dbuser,
                        UserModify(status=UserStatusModify.disabled),
                        commit=False,
                        inbound_cache=inbound_cache,
                    )
                _apply_usage_and_quota(dbuser, row)
                if row.sub_id and alias_endpoint_id:
                    _bind_sub_id_alias(
                        db,
                        user_id=dbuser.id,
                        sub_id=row.sub_id,
                        endpoint_id=alias_endpoint_id,
                    )
                    aliases += 1
            existing.add(row.username)
            existing_ids[row.username] = dbuser.id
            created += 1
            pending += 1
            if remaining_slots is not None:
                remaining_slots -= 1
        except Exception as exc:
            errors.append(f"{row.username}: {exc}")
            continue

        if pending >= COMMIT_EVERY:
            db.commit()
            db.expire_all()
            pending = 0

    if pending:
        db.commit()

    if created or repaired:
        # One core sync for the whole batch — not N background add_user tasks.
        bg.add_task(xray.operations.sync_core_users_async, full=False)
    if created or aliases or repaired:
        logger.info(
            "Imported %s users (skipped=%s repaired=%s aliases=%s errors=%s) in %.0fms",
            created,
            skipped,
            repaired,
            aliases,
            len(errors),
            (time.perf_counter() - t0) * 1000,
        )
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
