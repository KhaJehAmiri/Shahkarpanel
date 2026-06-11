"""Phase 6: white-label tenants, branding, BYO-node billing, SSH provisioning
and Iran<->foreign tunnels."""
import json

import pytest

from app import billing, provisioning
from app import tenant as tenant_svc
from app import tunnel as tunnel_svc
from app.db import GetDB
from app.db.models import Admin, Tunnel, User
from app.models.user import UserStatus


# --------------------------------------------------------------------------- #
# Tenant CRUD + slug uniqueness
# --------------------------------------------------------------------------- #
def test_slugify():
    assert tenant_svc.slugify("My Brand!") == "my-brand"
    assert tenant_svc.slugify("  ") == "tenant"


def test_create_tenant_unique_slug():
    with GetDB() as db:
        a = tenant_svc.create_tenant(db, name="Acme", slug="acme")
        b = tenant_svc.create_tenant(db, name="Acme 2", slug="acme")
        assert a.slug == "acme"
        assert b.slug == "acme-2"
        assert tenant_svc.get_tenant_by_slug(db, "acme").id == a.id


def test_byo_discount_percent_clamped():
    with GetDB() as db:
        t = tenant_svc.create_tenant(db, name="Clamp", byo_node_discount_percent=150)
        assert t.byo_node_discount_percent == 100
        t = tenant_svc.update_tenant(db, t, byo_node_discount_percent=-5)
        assert t.byo_node_discount_percent == 0


# --------------------------------------------------------------------------- #
# Scoping: reseller confined to their tenant
# --------------------------------------------------------------------------- #
def test_admin_tenant_scoping():
    with GetDB() as db:
        t = tenant_svc.create_tenant(db, name="ScopeCo")
        reseller = Admin(username="scope-reseller", hashed_password="x",
                         is_sudo=False, role="reseller", tenant_id=t.id)
        owner = Admin(username="scope-owner", hashed_password="x", is_sudo=True)
        db.add_all([reseller, owner])
        db.commit()
        db.refresh(reseller)

        u_in = User(username="scoped-in", status=UserStatus.active, admin_id=reseller.id)
        u_out = User(username="scoped-out", status=UserStatus.active, admin_id=owner.id)
        db.add_all([u_in, u_out])
        db.commit()

        # Sudo owner: no scoping.
        class _A:  # minimal admin stub
            is_sudo = True
            username = "scope-owner"
        assert tenant_svc.admin_tenant_id(db, _A()) is None

        class _R:
            is_sudo = False
            username = "scope-reseller"
        tid = tenant_svc.admin_tenant_id(db, _R())
        assert tid == t.id

        scoped = tenant_svc.scope_users_query(db.query(User), tid).all()
        usernames = {u.username for u in scoped}
        assert "scoped-in" in usernames
        assert "scoped-out" not in usernames


# --------------------------------------------------------------------------- #
# Branding resolution: tenant overrides global default
# --------------------------------------------------------------------------- #
def test_branding_resolution_layers():
    with GetDB() as db:
        tenant_svc.set_branding(db, None, allow_global=True, panel_title="Platform", primary_color="#111111")
        t = tenant_svc.create_tenant(db, name="BrandCo")
        tenant_svc.set_branding(db, t.id, panel_title="BrandCo Panel")

        resolved = tenant_svc.resolve_branding(db, t.id)
        # Tenant overrides title, inherits colour from the global layer.
        assert resolved["panel_title"] == "BrandCo Panel"
        assert resolved["primary_color"] == "#111111"

        # Unknown tenant -> falls back to the global default.
        base = tenant_svc.resolve_branding(db, None)
        assert base["panel_title"] == "Platform"


# --------------------------------------------------------------------------- #
# BYO-node discount billing math
# --------------------------------------------------------------------------- #
def test_effective_rate():
    assert billing.effective_rate(1000, 0) == 1000
    assert billing.effective_rate(1000, 40) == 600
    assert billing.effective_rate(1000, 100) == 0
    # Clamp + never negative.
    assert billing.effective_rate(1000, 200) == 0
    assert billing.effective_rate(1000, -10) == 1000


def test_usage_cost_split():
    # 10 GB on own nodes (40% off) + 5 GB on owner nodes, base 100/GB.
    cost = billing.usage_cost(base_rate=100, owned_units=10, foreign_units=5, discount_percent=40)
    assert cost == 10 * 60 + 5 * 100  # 600 + 500 = 1100


# --------------------------------------------------------------------------- #
# SSH provisioning: install-command builder
# --------------------------------------------------------------------------- #
def test_build_install_command_basic():
    cmd = provisioning.build_install_command(
        "panel.example.com", "tok123", "de-node-1", tenant_id=7, role="exit",
    )
    assert "get.docker.com" in cmd
    assert "http://panel.example.com/api/node/bootstrap" in cmd
    assert "tok123" in cmd
    assert "de-node-1" in cmd
    assert '"tenant_id":7' in cmd or '"tenant_id": 7' in cmd
    assert '"role":"exit"' in cmd or '"role": "exit"' in cmd
    assert "'\"$PUBLIC_IP\"'" in cmd


def test_build_install_command_enables_wireguard_and_v2ray():
    # Host ip_forward + NET_ADMIN; no container --sysctl with --network=host.
    cmd = provisioning.build_install_command(
        "panel.example.com", "tok", "n", control_secret="s3cr3t",
    )
    assert "--cap-add=NET_ADMIN" in cmd
    assert "sysctl -w net.ipv4.ip_forward=1" in cmd
    assert "--sysctl net.ipv4.ip_forward" not in cmd
    assert "NODE_CONTROL_SECRET=s3cr3t" in cmd


def test_build_install_command_omits_secret_when_unset():
    cmd = provisioning.build_install_command("panel.example.com", "tok", "n")
    assert "NODE_CONTROL_SECRET" not in cmd


def test_build_install_command_preserves_explicit_scheme():
    cmd = provisioning.build_install_command("http://1.2.3.4:8000", "t", "n")
    assert "http://1.2.3.4:8000/api/node/bootstrap" in cmd
    # default role, no tenant
    assert "tenant_id" not in cmd
    assert '"role":"direct"' in cmd or '"role": "direct"' in cmd
    assert "'\"$PUBLIC_IP\"'" in cmd


def test_build_install_command_json_escapes_quotes():
    cmd = provisioning.build_install_command("panel.example.com", "tok", 'node"evil', role="direct")
    assert '\\"name\\":\\"node\\\\\\"evil\\"' in cmd or '"name":"node\\"evil"' in cmd


def test_build_install_command_wireguard_core_kind():
    cmd = provisioning.build_install_command(
        "panel.example.com", "tok", "wg-1", core_kind="wireguard", region="eu",
    )
    assert '"core_kind":"wireguard"' in cmd or '"core_kind": "wireguard"' in cmd
    assert '"region":"eu"' in cmd or '"region": "eu"' in cmd


def test_build_install_command_builds_image_from_panel_bundle():
    cmd = provisioning.build_install_command("http://1.2.3.4:8000", "tok", "n1")
    assert "/api/nodes/agent-bundle?token=tok" in cmd
    assert "docker build -t" in cmd
    assert '"$NP_IMG"' in cmd


def test_build_install_command_validates():
    with pytest.raises(provisioning.ProvisioningError):
        provisioning.build_install_command("", "t", "n")
    with pytest.raises(provisioning.ProvisioningError):
        provisioning.build_install_command("p", "", "n")
    with pytest.raises(provisioning.ProvisioningError):
        provisioning.build_install_command("p", "t", "n", role="bogus")
    with pytest.raises(provisioning.ProvisioningError):
        provisioning.build_install_command("p", "t", "n", core_kind="bogus")


def test_run_remote_command_without_paramiko_is_graceful(monkeypatch):
    # Simulate paramiko missing: ssh_available False and run raises Unavailable.
    if not provisioning.ssh_available():
        creds = provisioning.SSHCredentials(host="1.1.1.1", password="x")
        with pytest.raises(provisioning.ProvisioningUnavailable):
            provisioning.run_remote_command(creds, "echo hi")
    else:
        pytest.skip("paramiko installed in this environment")


# --------------------------------------------------------------------------- #
# Tunnel config generation
# --------------------------------------------------------------------------- #
def test_default_params_per_transport():
    r = tunnel_svc.default_params("reality")
    assert {"id", "sni", "short_id"} <= set(r)
    ws = tunnel_svc.default_params("ws")
    assert ws["path"] == "/tunnel"
    with pytest.raises(ValueError):
        tunnel_svc.default_params("nope")


def _make_tunnel(transport="reality", params=None):
    return Tunnel(
        id=42, name="ir-de", enabled=True,
        relay_node_id=1, exit_node_id=2,
        transport=transport, listen_port=443, target_port=8443,
        params=params or tunnel_svc.default_params(transport),
    )


def test_build_tunnel_pair_reality():
    t = _make_tunnel("reality")
    pair = tunnel_svc.build_tunnel_pair(t, exit_address="de.example.com")

    out = pair["relay"]["outbound"]
    assert out["protocol"] == "vless"
    assert out["settings"]["vnext"][0]["address"] == "de.example.com"
    assert out["settings"]["vnext"][0]["port"] == 8443
    assert out["streamSettings"]["security"] == "reality"
    # client side gets publicKey, not privateKey
    assert "publicKey" in out["streamSettings"]["realitySettings"]
    assert "privateKey" not in out["streamSettings"]["realitySettings"]

    # Default relay routing is catch-all (dedicated relay box) -> tunnel outbound.
    rule = pair["relay"]["routing_rule"]
    assert rule["outboundTag"] == "tunnel-42-out"
    assert "inboundTag" not in rule
    assert rule["network"] == "tcp,udp"

    # Scoped routing pins specific user inbound tags to the tunnel outbound.
    scoped = tunnel_svc.build_tunnel_pair(
        t, "de.example.com", relay_inbound_tags=["vless-in", "vmess-in"]
    )
    assert scoped["relay"]["routing_rule"]["inboundTag"] == ["vless-in", "vmess-in"]

    # WireGuard-over-Reality adds a dokodemo-door UDP capture on the relay.
    wg = tunnel_svc.build_tunnel_pair(t, "de.example.com", wireguard_port=51820)
    wg_inbound = wg["relay"]["wireguard_inbound"]
    assert wg_inbound["protocol"] == "dokodemo-door"
    assert wg_inbound["port"] == 51820
    assert wg_inbound["settings"]["network"] == "udp"

    inb = pair["exit"]["inbound"]
    assert inb["port"] == 8443
    assert inb["protocol"] == "vless"
    # server side gets privateKey
    assert "privateKey" in inb["streamSettings"]["realitySettings"]

    # Config fragments must be JSON-serialisable.
    json.dumps(pair)


def test_build_tunnel_pair_ws_and_grpc():
    ws = tunnel_svc.build_tunnel_pair(_make_tunnel("ws"), "ex")
    assert ws["relay"]["outbound"]["streamSettings"]["network"] == "ws"
    assert ws["relay"]["outbound"]["streamSettings"]["wsSettings"]["path"] == "/tunnel"

    grpc = tunnel_svc.build_tunnel_pair(_make_tunnel("grpc"), "ex")
    assert grpc["exit"]["inbound"]["streamSettings"]["network"] == "grpc"


# --------------------------------------------------------------------------- #
# Per-endpoint tunnel injection (panel-local core as a tunnel end)
# --------------------------------------------------------------------------- #
def _base_xray_config():
    from app.xray.config import XRayConfig
    return XRayConfig({
        "log": {"logLevel": "warning"},
        "inbounds": [{
            "tag": "vless-in",
            "protocol": "vless",
            "port": 443,
            "settings": {"clients": []},
            "streamSettings": {"network": "tcp"},
        }],
        "outbounds": [{"tag": "direct", "protocol": "freedom"}],
    })


def test_inject_panel_as_relay_adds_outbound_and_routing():
    from app.db.models import Node
    from app.tunnel.inject import apply_endpoint_tunnels

    with GetDB() as db:
        exit_node = Node(name="de-exit", address="de.example.com", port=62050, api_port=62051)
        db.add(exit_node)
        db.commit()
        db.refresh(exit_node)
        t = Tunnel(
            name="panel-relay", enabled=True,
            relay_node_id=None, exit_node_id=exit_node.id,
            transport="reality", listen_port=8443, target_port=9443,
            params=tunnel_svc.default_params("reality"),
        )
        db.add(t)
        db.commit()
        tid, exit_addr = t.id, exit_node.address

    cfg = _base_xray_config()
    out = apply_endpoint_tunnels(cfg, None)  # panel is the relay end

    tags = {ob.get("tag") for ob in out["outbounds"]}
    assert f"tunnel-{tid}-out" in tags
    ob = next(ob for ob in out["outbounds"] if ob["tag"] == f"tunnel-{tid}-out")
    assert ob["settings"]["vnext"][0]["address"] == exit_addr
    # User inbound traffic is pinned to the tunnel outbound.
    pinned = [r for r in out["routing"]["rules"] if r.get("outboundTag") == f"tunnel-{tid}-out"]
    assert pinned and "vless-in" in pinned[0]["inboundTag"]


def test_inject_panel_as_exit_adds_inbound():
    from app.db.models import Node
    from app.tunnel.inject import apply_endpoint_tunnels

    with GetDB() as db:
        relay_node = Node(name="ir-relay", address="1.2.3.4", port=62050, api_port=62051)
        db.add(relay_node)
        db.commit()
        db.refresh(relay_node)
        t = Tunnel(
            name="panel-exit", enabled=True,
            relay_node_id=relay_node.id, exit_node_id=None,
            transport="reality", listen_port=8443, target_port=9443,
            params=tunnel_svc.default_params("reality"),
        )
        db.add(t)
        db.commit()
        tid = t.id

    cfg = _base_xray_config()
    out = apply_endpoint_tunnels(cfg, None)  # panel is the exit end

    in_tags = {ib.get("tag") for ib in out["inbounds"]}
    assert f"tunnel-{tid}-exit" in in_tags
    inb = next(ib for ib in out["inbounds"] if ib["tag"] == f"tunnel-{tid}-exit")
    assert inb["port"] == 9443
    assert "privateKey" in inb["streamSettings"]["realitySettings"]
