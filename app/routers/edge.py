from dataclasses import asdict

from fastapi import APIRouter, Depends

from app.db import Session, get_db
from app.models.admin import Admin
from app.services.edge_proxy import edge_status, sync_edge_nginx
from app.utils import responses

router = APIRouter(tags=["Edge"], prefix="/api", responses={401: responses._401})


@router.get("/edge/status", responses={403: responses._403})
def get_edge_status(
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
) -> dict:
    """CDN edge proxy routes and nginx reconcile status."""
    return edge_status(db)


@router.post("/edge/reconcile", responses={403: responses._403})
def reconcile_edge(
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
) -> dict:
    """Re-apply nginx edge configs from current hosts + inbounds."""
    from app import xray

    from app.services.edge_proxy import cdn_runtime_enabled, sync_edge_nginx

    result = sync_edge_nginx(db)
    if result.routes or cdn_runtime_enabled():
        xray.core.restart(xray.config.include_db_users())
    return {
        "routes": [asdict(r) for r in result.routes],
        "nginx_applied": result.nginx_applied,
        "message": result.nginx_message,
        "warnings": result.warnings,
    }
