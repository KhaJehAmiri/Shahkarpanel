"""Editing a user must not regenerate existing proxy credentials."""
import uuid

from app.db import GetDB, crud
from app.models.proxy import ProxyTypes, apply_proxy_patch
from app.models.user import UserCreate, UserModify, UserStatusCreate


def test_apply_proxy_patch_preserves_vless_uuid():
    existing = {"id": "11111111-1111-1111-1111-111111111111", "flow": ""}
    patch = {"flow": "xtls-rprx-vision"}  # panel-style partial edit
    out = apply_proxy_patch(ProxyTypes.VLESS, existing, patch)
    assert out["id"] == "11111111-1111-1111-1111-111111111111"
    assert out["flow"] == "xtls-rprx-vision"


def test_apply_proxy_patch_preserves_shadowsocks_password():
    existing = {"password": "keep-me", "method": "chacha20-ietf-poly1305"}
    patch = {"method": "aes-256-gcm"}
    out = apply_proxy_patch(ProxyTypes.Shadowsocks, existing, patch)
    assert out["password"] == "keep-me"
    assert out["method"] == "aes-256-gcm"


def test_apply_proxy_patch_new_wireguard_generates_keys():
    out = apply_proxy_patch(ProxyTypes.WireGuard, None, {})
    assert out["private_key"]
    assert out["public_key"]


def test_update_user_add_wireguard_keeps_vless_uuid():
    """Reproduce panel edit: enable WG while sending partial VLESS patch."""
    with GetDB() as db:
        created = crud.create_user(
            db,
            UserCreate(
                username=f"cred-{uuid.uuid4().hex[:8]}",
                status=UserStatusCreate.active,
                proxies={ProxyTypes.VLESS: {}},
                inbounds={},
            ),
        )
        original_id = next(
            p.settings["id"] for p in created.proxies if p.type == ProxyTypes.VLESS.value
        )

        modify = UserModify(
            proxies={
                ProxyTypes.VLESS: {"flow": ""},
                ProxyTypes.WireGuard: {},
            },
        )
        updated = crud.update_user(db, created, modify)
        db.refresh(updated)

        by_type = {ProxyTypes(p.type): p for p in updated.proxies}
        assert by_type[ProxyTypes.VLESS].settings["id"] == original_id
        assert by_type[ProxyTypes.WireGuard].settings["private_key"]
