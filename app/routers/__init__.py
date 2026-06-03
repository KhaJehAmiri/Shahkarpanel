from fastapi import APIRouter

from . import (
    admin,
    analytics,
    api_keys,
    backup,
    billing,
    core,
    feature_flags,
    home,
    intelligence,
    marketplace,
    metrics,
    node,
    plans,
    plugins,
    protocols,
    provisioning,
    routing,
    rules,
    setup,
    subscription,
    system,
    tenant,
    tunnel,
    user,
    user_template,
    v2,
    workflows,
)

api_router = APIRouter()

routers = [
    admin.router,
    analytics.router,
    api_keys.router,
    backup.router,
    billing.router,
    core.router,
    feature_flags.router,
    intelligence.router,
    marketplace.router,
    metrics.router,
    node.router,
    plans.router,
    plugins.router,
    protocols.router,
    provisioning.router,
    routing.router,
    rules.router,
    setup.router,
    subscription.router,
    system.router,
    tenant.router,
    tunnel.router,
    user_template.router,
    user.router,
    v2.router,
    workflows.router,
    home.router,
]

for router in routers:
    api_router.include_router(router)

__all__ = ["api_router"]