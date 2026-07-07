"""panel service catalog + node bindings

Revision ID: j6k7l8m9n0o1
Revises: i5j6k7l8m9n0
Create Date: 2026-06-10 14:00:00.000000

"""
import json

import sqlalchemy as sa
from alembic import op

revision = "j6k7l8m9n0o1"
down_revision = "i5j6k7l8m9n0"
branch_labels = None
depends_on = None

SERVICE_SEEDS = [
    ("xray", "Xray (all product inbounds)", "xray", "xray", {"mode": "all_inbounds"}, 10),
    ("wireguard-plain", "WireGuard", "wireguard", "wireguard", {"listen_port": 51820, "subnet": "10.10.0.0/24"}, 20),
    ("amneziawg", "AmneziaWG", "wireguard", "amneziawg", {"awg_listen_port": 51821, "awg_subnet": "10.11.0.0/24"}, 21),
    ("hysteria2", "Hysteria2", "singbox", "hysteria2", {"port": 44333}, 30),
    ("tuic", "TUIC", "singbox", "tuic", {"port": 44334, "congestion_control": "bbr"}, 31),
    ("anytls", "AnyTLS", "singbox", "anytls", {"port": 44335}, 32),
]


def upgrade() -> None:
    op.create_table(
        "panel_services",
        sa.Column("slug", sa.String(64), primary_key=True),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("engine", sa.String(16), nullable=False),
        sa.Column("protocol", sa.String(32), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_table(
        "node_service_bindings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("node_id", sa.Integer(), sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("service_slug", sa.String(64), sa.ForeignKey("panel_services.slug"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("overrides", sa.JSON(), nullable=True),
        sa.UniqueConstraint("node_id", "service_slug"),
    )
    op.create_index("ix_node_service_bindings_node_id", "node_service_bindings", ["node_id"])

    conn = op.get_bind()
    for slug, name, engine, protocol, cfg, order in SERVICE_SEEDS:
        conn.execute(
            sa.text(
                "INSERT INTO panel_services (slug, display_name, engine, protocol, config, is_active, sort_order) "
                "VALUES (:slug, :name, :engine, :protocol, :config, true, :ord)"
            ),
            {"slug": slug, "name": name, "engine": engine, "protocol": protocol, "config": json.dumps(cfg), "ord": order},
        )

    def _bind(node_id: int, service_slug: str) -> None:
        exists = conn.execute(
            sa.text(
                "SELECT 1 FROM node_service_bindings WHERE node_id = :nid AND service_slug = :slug"
            ),
            {"nid": node_id, "slug": service_slug},
        ).fetchone()
        if exists:
            return
        conn.execute(
            sa.text(
                "INSERT INTO node_service_bindings (node_id, service_slug, enabled) "
                "VALUES (:nid, :slug, true)"
            ),
            {"nid": node_id, "slug": service_slug},
        )

    rows = conn.execute(sa.text("SELECT id, core_kind FROM nodes")).fetchall()
    for node_id, core_kind in rows:
        if core_kind == "wireguard":
            _bind(node_id, "wireguard-plain")
        elif core_kind == "xray":
            _bind(node_id, "xray")

        sb = conn.execute(
            sa.text(
                "SELECT hysteria2_enabled, tuic_enabled, anytls_enabled FROM node_singbox WHERE node_id = :nid"
            ),
            {"nid": node_id},
        ).fetchone()
        if sb:
            hy2, tuic, at = sb
            if hy2:
                _bind(node_id, "hysteria2")
            if tuic:
                _bind(node_id, "tuic")
            if at:
                _bind(node_id, "anytls")

        wg = conn.execute(
            sa.text(
                "SELECT plain_enabled, awg_enabled FROM node_wireguard WHERE node_id = :nid"
            ),
            {"nid": node_id},
        ).fetchone()
        if wg:
            plain, awg = wg
            if plain:
                _bind(node_id, "wireguard-plain")
            if awg:
                _bind(node_id, "amneziawg")


def downgrade() -> None:
    op.drop_index("ix_node_service_bindings_node_id", "node_service_bindings")
    op.drop_table("node_service_bindings")
    op.drop_table("panel_services")
