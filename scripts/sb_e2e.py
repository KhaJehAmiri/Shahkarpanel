"""E2E smoke for sing-box (Hysteria2 / TUIC) config + subscription links.

Creates a sing-box-enabled node row, an active user with hysteria2+tuic proxies,
and prints subscription tokens/URLs for external curl validation.
"""
import json
import uuid

from app.db import GetDB, crud
from app.models.node import NodeCreate
from app.models.user import UserCreate, UserStatus
from app.subscription.quic import user_hysteria2_link, user_tuic_link
from app.utils.jwt import create_subscription_token

out = {}
with GetDB() as db:
    node = crud.create_node(
        db,
        NodeCreate(
            name=f"sb-e2e-{uuid.uuid4().hex[:6]}",
            address="127.0.0.1",
            port=62050,
            api_port=62051,
            core_kind="wireguard",
        ),
    )
    crud.upsert_node_singbox(
        db,
        node,
        certificate_path="/var/lib/nexuspanel-node/tls/cert.pem",
        key_path="/var/lib/nexuspanel-node/tls/key.pem",
        sni="127.0.0.1",
        hysteria2_enabled=True,
        hysteria2_port=44333,
        tuic_enabled=True,
        tuic_port=44334,
    )
    out["node_id"] = node.id

    user = crud.create_user(
        db,
        UserCreate(
            username=f"sbok{uuid.uuid4().hex[:6]}",
            proxies={"hysteria2": {}, "tuic": {}},
            inbounds={},
            status="active",
            data_limit=0,
        ),
    )
    out["user"] = user.username
    out["token"] = create_subscription_token(user.username)

    hy2_settings = next(p.settings for p in user.proxies if p.type.value == "hysteria2")
    tuic_settings = next(p.settings for p in user.proxies if p.type.value == "tuic")
    db.refresh(node)
    out["hysteria2_link"] = user_hysteria2_link(hy2_settings, node, remark=user.username)
    out["tuic_link"] = user_tuic_link(tuic_settings, node, remark=user.username)
    out["singbox_nodes"] = [n.id for n in crud.get_singbox_nodes(db)]

    limited = crud.create_user(
        db,
        UserCreate(
            username=f"sblim{uuid.uuid4().hex[:6]}",
            proxies={"hysteria2": {}},
            inbounds={},
            status="active",
            data_limit=1000,
        ),
    )
    limited.used_traffic = 5000
    limited.status = UserStatus.limited
    db.commit()
    out["limited_user"] = limited.username
    out["limited_token"] = create_subscription_token(limited.username)

print(json.dumps(out, indent=2))
