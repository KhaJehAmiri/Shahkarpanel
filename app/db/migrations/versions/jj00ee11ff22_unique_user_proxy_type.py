"""One proxy row per user per protocol.

Duplicate WireGuard rows (same tunnel IP, different keys) made subscription
export one key while Finalmask baked the other.

Revision ID: jj00ee11ff22
Revises: ii99dd00ee11
Create Date: 2026-08-18
"""
from alembic import op
import sqlalchemy as sa


revision = "jj00ee11ff22"
down_revision = "ii99dd00ee11"
branch_labels = None
depends_on = None


def _dedupe_postgres(conn) -> None:
    # Keep the row whose public_key matches wg_peers, else the newest id.
    conn.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT p.id,
                    ROW_NUMBER() OVER (
                        PARTITION BY p.user_id, p.type
                        ORDER BY
                            CASE
                                WHEN p.type::text = 'WireGuard'
                                 AND w.public_key IS NOT NULL
                                 AND COALESCE(p.settings->>'public_key', '') = w.public_key
                                THEN 0 ELSE 1
                            END,
                            p.id DESC
                    ) AS rn
                FROM proxies p
                LEFT JOIN wg_peers w ON w.user_id = p.user_id
                WHERE p.user_id IS NOT NULL
            )
            DELETE FROM exclude_inbounds_association
            WHERE proxy_id IN (SELECT id FROM ranked WHERE rn > 1)
            """
        )
    )
    conn.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT p.id,
                    ROW_NUMBER() OVER (
                        PARTITION BY p.user_id, p.type
                        ORDER BY
                            CASE
                                WHEN p.type::text = 'WireGuard'
                                 AND w.public_key IS NOT NULL
                                 AND COALESCE(p.settings->>'public_key', '') = w.public_key
                                THEN 0 ELSE 1
                            END,
                            p.id DESC
                    ) AS rn
                FROM proxies p
                LEFT JOIN wg_peers w ON w.user_id = p.user_id
                WHERE p.user_id IS NOT NULL
            )
            DELETE FROM proxies
            WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
            """
        )
    )


def _dedupe_generic(conn) -> None:
    rows = conn.execute(
        sa.text(
            "SELECT id, user_id, type, settings FROM proxies "
            "WHERE user_id IS NOT NULL ORDER BY id ASC"
        )
    ).fetchall()
    peer_rows = conn.execute(
        sa.text("SELECT user_id, public_key FROM wg_peers")
    ).fetchall()
    peer_keys = {r[0]: (r[1] or "") for r in peer_rows}

    groups: dict[tuple, list] = {}
    for row in rows:
        groups.setdefault((row[1], str(row[2])), []).append(row)

    drop_ids: list[int] = []
    for (user_id, ptype), items in groups.items():
        if len(items) < 2:
            continue
        wg_key = peer_keys.get(user_id, "")
        keep = None
        if str(ptype) in ("WireGuard", "wireguard") and wg_key:
            for item in items:
                settings = item[3] or {}
                if isinstance(settings, str):
                    import json

                    try:
                        settings = json.loads(settings)
                    except Exception:
                        settings = {}
                if isinstance(settings, dict) and settings.get("public_key") == wg_key:
                    keep = item
                    break
        if keep is None:
            keep = max(items, key=lambda r: int(r[0]))
        drop_ids.extend(int(item[0]) for item in items if item[0] != keep[0])

    if not drop_ids:
        return
    # chunk deletes
    for i in range(0, len(drop_ids), 500):
        chunk = drop_ids[i : i + 500]
        bind = ",".join(str(int(x)) for x in chunk)
        conn.execute(
            sa.text(
                f"DELETE FROM exclude_inbounds_association WHERE proxy_id IN ({bind})"
            )
        )
        conn.execute(sa.text(f"DELETE FROM proxies WHERE id IN ({bind})"))


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        _dedupe_postgres(conn)
    else:
        _dedupe_generic(conn)

    op.create_unique_constraint(
        "uq_proxies_user_id_type",
        "proxies",
        ["user_id", "type"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_proxies_user_id_type", "proxies", type_="unique")
