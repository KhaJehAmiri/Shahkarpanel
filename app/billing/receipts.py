"""Card-to-card payment receipt storage with content sanitization.

Uploads are accepted only after:
  1. Size limit check
  2. Magic-byte type sniff (not client MIME / filename)
  3. Image re-encode via Pillow (strips EXIF / polyglots) or PDF rewrite via pypdf
     (rejects JavaScript, Launch, embedded files, encryption)
"""

from __future__ import annotations

import io
import os
import re
import uuid
from pathlib import Path
from typing import Optional, Tuple

from fastapi import HTTPException, UploadFile

RECEIPT_DIR = Path(
    os.environ.get("SHAHKAR_DATA_DIR", "/var/lib/shahkar")
) / "payment_receipts"

# Phone camera receipts are often 8–12 MB; keep headroom under a hard cap.
MAX_RECEIPT_BYTES = 15 * 1024 * 1024
MAX_RECEIPT_MB = MAX_RECEIPT_BYTES // (1024 * 1024)
# Decode budget — blocks decompression bombs before re-encode.
MAX_IMAGE_PIXELS = 40_000_000  # ~40 MP

ALLOWED_CONTENT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
}
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}

_SNIFF_JPEG = b"\xff\xd8\xff"
_SNIFF_PNG = b"\x89PNG\r\n\x1a\n"
_SNIFF_PDF = b"%PDF"


def sniff_receipt_type(data: bytes) -> Tuple[str, str]:
    """Detect receipt type from magic bytes. Returns (content_type, ext)."""
    if not data:
        raise HTTPException(status_code=400, detail="Empty receipt file")

    if data.startswith(_SNIFF_JPEG):
        return "image/jpeg", ".jpg"
    if data.startswith(_SNIFF_PNG):
        return "image/png", ".png"
    if data.startswith(_SNIFF_PDF):
        return "application/pdf", ".pdf"
    if len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", ".webp"

    raise HTTPException(
        status_code=400,
        detail="Receipt must be a real JPG, PNG, WEBP, or PDF file",
    )


def _reject(detail: str) -> None:
    raise HTTPException(status_code=400, detail=detail)


def _sanitize_image(data: bytes) -> Tuple[bytes, str, str]:
    """Re-encode any accepted image as clean JPEG (no EXIF / trailing payload)."""
    try:
        from PIL import Image, ImageFile
    except ImportError as exc:
        raise HTTPException(
            status_code=500,
            detail="Image sanitizer unavailable",
        ) from exc

    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    ImageFile.LOAD_TRUNCATED_IMAGES = False

    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()  # force full decode — fails on truncated / bomb payloads
            # Flatten animated / multi-frame to first frame only.
            if getattr(img, "n_frames", 1) > 1:
                img.seek(0)
            if img.mode in ("RGBA", "LA", "P"):
                rgba = img.convert("RGBA")
                bg = Image.new("RGB", rgba.size, (255, 255, 255))
                bg.paste(rgba, mask=rgba.split()[-1])
                rgb = bg
            else:
                rgb = img.convert("RGB")
            # Bound absurd dimensions even if pixel count slipped through.
            w, h = rgb.size
            if w < 8 or h < 8:
                _reject("Receipt image is too small")
            if w * h > MAX_IMAGE_PIXELS:
                _reject("Receipt image is too large")
            out = io.BytesIO()
            rgb.save(
                out,
                format="JPEG",
                quality=88,
                optimize=True,
                progressive=True,
            )
            clean = out.getvalue()
    except HTTPException:
        raise
    except Exception:
        _reject("Receipt image could not be verified")

    if not clean.startswith(_SNIFF_JPEG):
        _reject("Receipt image sanitization failed")
    if len(clean) > MAX_RECEIPT_BYTES:
        _reject(f"Receipt too large after processing (max {MAX_RECEIPT_MB} MB)")
    return clean, "image/jpeg", ".jpg"


_PDF_DANGEROUS_KEYS = {
    "/JavaScript",
    "/JS",
    "/EmbeddedFiles",
    "/EmbeddedFile",
    "/FileAttachment",
    "/Launch",
    "/SubmitForm",
    "/ImportData",
    "/GoToE",
    "/GoToR",
    "/RichMedia",
    "/XFA",
}


def _pdf_object_is_dangerous(obj, depth: int = 0) -> bool:
    """Walk PDF object graph for executable / attachment hooks."""
    if depth > 40 or obj is None:
        return False
    try:
        from pypdf.generic import DictionaryObject, ArrayObject, IndirectObject
    except ImportError:
        return False

    if isinstance(obj, IndirectObject):
        try:
            obj = obj.get_object()
        except Exception:
            return False
        return _pdf_object_is_dangerous(obj, depth + 1)

    if isinstance(obj, DictionaryObject):
        for key in obj.keys():
            name = str(key)
            if name in _PDF_DANGEROUS_KEYS:
                return True
            # Named actions often used for JS entry points.
            if name == "/S" and str(obj.get(key)) in ("/JavaScript", "/Launch", "/SubmitForm"):
                return True
        # Recurse values lightly (catalog / page / annot trees).
        for key in ("/OpenAction", "/AA", "/Names", "/AcroForm", "/Annots", "/Action", "/A"):
            if key in obj and _pdf_object_is_dangerous(obj[key], depth + 1):
                return True
        return False

    if isinstance(obj, ArrayObject):
        return any(_pdf_object_is_dangerous(item, depth + 1) for item in obj)

    return False


def _sanitize_pdf(data: bytes) -> Tuple[bytes, str, str]:
    """Reject active content; rewrite pages-only PDF without original trailer hooks."""
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError as exc:
        raise HTTPException(
            status_code=500,
            detail="PDF sanitizer unavailable",
        ) from exc

    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
    except Exception:
        _reject("Receipt PDF could not be verified")

    if getattr(reader, "is_encrypted", False):
        _reject("Encrypted PDF receipts are not allowed")

    try:
        n_pages = len(reader.pages)
    except Exception:
        _reject("Receipt PDF could not be verified")
    if n_pages < 1:
        _reject("Receipt PDF has no pages")
    if n_pages > 20:
        _reject("Receipt PDF has too many pages (max 20)")

    # Root / catalog dangerous features
    try:
        root = reader.trailer.get("/Root")
        if _pdf_object_is_dangerous(root):
            _reject("Receipt PDF contains disallowed active content")
        for page in reader.pages:
            if _pdf_object_is_dangerous(page.get_object() if hasattr(page, "get_object") else page):
                _reject("Receipt PDF contains disallowed active content")
    except HTTPException:
        raise
    except Exception:
        _reject("Receipt PDF could not be verified")

    try:
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        # Drop document-level metadata and outline that may carry actions.
        if hasattr(writer, "metadata"):
            writer.metadata = None
        out = io.BytesIO()
        writer.write(out)
        clean = out.getvalue()
    except Exception:
        _reject("Receipt PDF could not be sanitized")

    if not clean.startswith(_SNIFF_PDF):
        _reject("Receipt PDF sanitization failed")
    if len(clean) > MAX_RECEIPT_BYTES:
        _reject(f"Receipt too large after processing (max {MAX_RECEIPT_MB} MB)")
    return clean, "application/pdf", ".pdf"


def sanitize_receipt(data: bytes) -> Tuple[bytes, str, str]:
    """Sniff + sanitize. Returns (clean_bytes, content_type, ext)."""
    content_type, _ext = sniff_receipt_type(data)
    if content_type == "application/pdf":
        return _sanitize_pdf(data)
    return _sanitize_image(data)


def save_receipt(intent_id: int, upload: UploadFile) -> dict:
    """Persist a sanitized receipt under payment_receipts/{intent_id}/…."""
    if upload is None:
        raise HTTPException(status_code=400, detail="Receipt file is required")
    data = upload.file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty receipt file")
    if len(data) > MAX_RECEIPT_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Receipt too large (max {MAX_RECEIPT_MB} MB)",
        )

    clean, content_type, ext = sanitize_receipt(data)

    folder = RECEIPT_DIR / str(int(intent_id))
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{ext}"
    dest = folder / name
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(clean)
    tmp.replace(dest)
    rel = f"{int(intent_id)}/{name}"
    # Display name is UUID-based — never trust client filename for storage/UI identity.
    safe_name = f"receipt{ext}"
    return {
        "receipt_relpath": rel,
        "receipt_name": safe_name,
        "receipt_content_type": content_type,
        "receipt_size": len(clean),
        "receipt_original_size": len(data),
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
        return stored if stored != "image/jpg" else "image/jpeg"
    ext = path.suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".pdf": "application/pdf",
    }.get(ext, "application/octet-stream")


def receipt_response_headers() -> dict:
    """Hardened headers when serving stored receipts."""
    return {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Cache-Control": "private, no-store",
        "Content-Security-Policy": "default-src 'none'; sandbox; frame-ancestors 'none'",
    }
