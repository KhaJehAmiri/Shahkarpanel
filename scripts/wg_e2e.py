"""Phase 11.7 E2E smoke for WireGuard provisioning + .conf issuance.

Runs in-process against the live DB/app: creates a WG node + config, an active
WG user and an over-quota WG user, then exercises provisioning + gating.
Prints a JSON summary and the active user's subscription token so the HTTP
route can be validated externally with curl.
"""
import json
import uuid

from app.db import GetDB, crud
from app.db.models import Proxy, User
from app.models.node import NodeCreate
from app.models.proxy import ProxyTypes
from app.models.user import UserCreate, UserStatus
from app.utils.jwt import create_subscription_token
from app.wireguard import generate_keypair

out = {}
with GetDB() as db:
    # 1) WG node + server config
    srv_priv, srv_pub = generate_keypair()
    node = crud.create_node(db, NodeCreate(
        name=f"wg-e2e-{uuid.uuid4().hex[:6]}",
        address="127.0.0.1",
        port=62050,
        api_port=62051,
        core_kind="wireguard",
    ))
    crud.set_node_wireguard(
        db, node,
        interface="wg0", listen_port=51820, subnet="10.10.0.0/24",
        private_key=srv_priv, public_key=srv_pub,
        endpoint="212.100.171.208:51820", mtu=1420, dns="1.1.1.1",
    )
    out["node_id"] = node.id
    out["node_core_kind"] = node.core_kind
    out["wg_nodes_visible"] = [n.id for n in crud.get_wireguard_nodes(db)]

    # 2) active WG user
    active = crud.create_user(db, UserCreate(
        username=f"wgok{uuid.uuid4().hex[:6]}",
        proxies={"wireguard": {}},
        inbounds={},
        status="active",
        data_limit=0,
    ))
    out["active_user"] = active.username
    out["active_token"] = create_subscription_token(active.username)
    wg_proxy = next(p for p in active.proxies if p.type is ProxyTypes.WireGuard)
    out["active_has_pubkey"] = bool((wg_proxy.settings or {}).get("public_key"))
    out["active_address_before"] = (wg_proxy.settings or {}).get("address")

    # 3) over-quota WG user (limited)
    over = crud.create_user(db, UserCreate(
        username=f"wglim{uuid.uuid4().hex[:6]}",
        proxies={"wireguard": {}},
        inbounds={},
        status="active",
        data_limit=1000,
    ))
    over.used_traffic = 5000
    over.status = UserStatus.limited
    db.commit()
    out["over_user"] = over.username
    out["over_token"] = create_subscription_token(over.username)

print(json.dumps(out, indent=2))
