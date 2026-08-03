from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

from config import HOME_PAGE_TEMPLATE
from app.templates import render_template

router = APIRouter()

_NEXT_INDEX = Path(__file__).resolve().parent.parent / "dashboard-next" / "out" / "index.html"


def _next_landing() -> FileResponse | None:
    if _NEXT_INDEX.is_file():
        return FileResponse(_NEXT_INDEX, media_type="text/html")
    return None


@router.get("/", response_class=HTMLResponse)
def base():
    nxt = _next_landing()
    if nxt is not None:
        return nxt
    return render_template(HOME_PAGE_TEMPLATE)


@router.get("/t/{slug}", response_class=HTMLResponse)
@router.get("/t/{slug}/", response_class=HTMLResponse)
def tenant_landing(slug: str):
    """White-label landing for a reseller slug (same Next storefront SPA)."""
    nxt = _next_landing()
    if nxt is not None:
        return nxt
    return render_template(HOME_PAGE_TEMPLATE)
