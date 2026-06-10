"""Post-provision sing-box defaults and service wiring."""
from app.db import GetDB, crud
from app.models.node import CoreKind, NodeCreate
from app.provisioning import SSHCredentials
from app.provisioning.post_install import ProvisionExtras, run_post_provision


def test_provision_singbox_defaults():
    with GetDB() as db:
        node = crud.create_node(
            db,
            NodeCreate(name="post-sb-1", address="10.0.0.5", port=62050, api_port=62051),
        )
        cfg = crud.provision_singbox_defaults(db, node, hysteria2=True, tuic=True, sni="10.0.0.5")
        assert cfg.hysteria2_enabled is True
        assert cfg.hysteria2_port == 44333
        assert cfg.tuic_enabled is True
        assert cfg.tuic_port == 44334
        assert cfg.sni == "10.0.0.5"
        assert cfg.certificate_path.endswith("cert.pem")


def test_post_install_singbox_on_wireguard_core(monkeypatch):
    """WireGuard core nodes can enable Hysteria2 during provision (no SSH)."""
    monkeypatch.setattr(
        "app.tls.self_signed.install_self_signed",
        lambda *a, **k: "SELF_SIGNED",
    )
    monkeypatch.setattr("app.provisioning.post_install._sync_singbox", lambda _nid: None)
    monkeypatch.setattr("app.provisioning.post_install._maybe_create_tunnel", lambda *a: None)
    monkeypatch.setattr("app.xray.operations.connect_node", lambda _nid: None)

    with GetDB() as db:
        node = crud.create_node(
            db,
            NodeCreate(
                name="wg-hy2",
                address="10.0.0.8",
                port=62050,
                api_port=62051,
                core_kind=CoreKind.wireguard,
            ),
        )
        crud.provision_wireguard_defaults(db, node)
        node_id = node.id

    extras = ProvisionExtras(enable_hysteria2=True, enable_tuic=False, tls_mode="self_signed")
    run_post_provision(node_id, SSHCredentials(host="10.0.0.8", password="x"), extras)

    with GetDB() as db:
        dbnode = crud.get_node_by_id(db, node_id)
        assert dbnode.singbox is not None
        assert dbnode.singbox.hysteria2_enabled is True
        assert dbnode.singbox.sni == "10.0.0.8"
