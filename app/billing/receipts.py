"""Card-to-card payment receipt storage."""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, UploadFile

RECEIPT_DIR = Path(
    os.environ.get("SHAHKAR_DATA_DIR", "/var/lib/shahkar")
) / "payment_receipts"

MAX_RECEIPT_BYTES = 5 * 1024 * 1024
ALLOWED_CONTENT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
}
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}


def _safe_ext(filename: str, content_type: Optional[str]) -> str:
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype in ALLOWED_CONTENT:
        return ALLOWED_CONTENT[ctype]
    ext = Path(filename or "").suffix.lower()
    if ext == ".jpeg":
        ext = ".jpg"
    if ext in ALLOWED_EXT:
        return ext
    raise HTTPException(
        status_code=400,
        detail="Receipt must be JPG, PNG, WEBP, or PDF",
    )


def save_receipt(intent_id: int, upload: UploadFile) -> dict:
    """Persist upload under payment_receipts/{intent_id}/…; return meta for intent.extra."""
    if upload is None:
        raise HTTPException(status_code=400, detail="Receipt file is required")
    data = upload.file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty receipt file")
    if len(data) > MAX_RECEIPT_BYTES:
        raise HTTPException(status_code=400, detail="Receipt too large (max 5 MB)")
    ext = _safe_ext(upload.filename or "", upload.content_type)
    folder = RECEIPT_DIR / str(int(intent_id))
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{ext}"
    dest = folder / name
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(dest)
    rel = f"{int(intent_id)}/{name}"
    return {
        "receipt_relpath": rel,
        "receipt_name": (upload.filename or name)[:200],
        "receipt_content_type": (upload.content_type or "")[:100],
        "receipt_size": len(data),
    }


def resolve_receipt_path(relpath: str) -> Path:
    """Resolve a stored relative path; reject path traversal."""
    rel = (relpath or "").strip().lstrip("/")
    if not rel or ".." in rel or rel.startswith("/") or "\\" in rel:
        raise HTTPException(status_code=404, detail="Receipt not found")
    if not re.match(r"^\d+/[a-zA-Z0-9._-]+$", rel):
        raise HTTPException(status_code=404, detail="Receipt not found")
    full = (RECEIPT_DIR / rel).resolve()
    try:
        full.relative_to(RECEIPT_DIR.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Receipt not found") from exc
    if not full.is_file():
        raise HTTPException(status_code=404, detail="Receipt not found")
    return full


def receipt_media_type(path: Path, stored: Optional[str] = None) -> str:
    if stored and stored in ALLOWED_CONTENT:
        return stored
    ext = path.suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".pdf": "application/pdf",
    }.get(ext, "application/octet-stream")
