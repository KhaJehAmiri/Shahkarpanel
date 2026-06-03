"""One-off SQLite -> PostgreSQL data migration for NexusPanel.

Assumptions:
  * The destination PostgreSQL schema already exists (run ``alembic upgrade
    head`` against the PG URL first).
  * ``SQLALCHEMY_DATABASE_URL`` in the environment points at the *destination*
    PostgreSQL database (this is what the app will use after cutover).
  * The source SQLite file path is passed via ``--sqlite`` (default
    ``/var/lib/nexuspanel/db.sqlite3``).

Copies every ORM-mapped table in FK-safe order using the typed metadata so
JSON / Enum / Boolean / DateTime columns round-trip correctly, then fixes the
PostgreSQL ``id`` sequences. Aborts (no partial commit) if any *non-empty*
SQLite table is missing from the ORM metadata, to guarantee no silent data
loss.
"""
import argparse
import os
import sys

from sqlalchemy import create_engine, inspect, select, text

from app.db import Base  # noqa: F401  (registers all ORM tables)
import app.db.models  # noqa: F401


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", default="/var/lib/nexuspanel/db.sqlite3")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    pg_url = os.environ.get("SQLALCHEMY_DATABASE_URL", "")
    if not pg_url.startswith("postgresql"):
        print(f"ABORT: SQLALCHEMY_DATABASE_URL is not PostgreSQL: {pg_url!r}")
        return 2

    src = create_engine(f"sqlite:///{args.sqlite}")
    dst = create_engine(pg_url)

    meta = Base.metadata
    mapped = {t.name for t in meta.sorted_tables}

    # Guard: any non-empty sqlite table not represented in ORM metadata?
    src_insp = inspect(src)
    sqlite_tables = set(src_insp.get_table_names())
    with src.connect() as s:
        nonempty = {}
        for t in sqlite_tables:
            if t == "alembic_version":
                continue
            n = s.execute(text(f'SELECT count(*) FROM "{t}"')).scalar() or 0
            if n:
                nonempty[t] = n
    missing = [t for t in nonempty if t not in mapped]
    if missing:
        print("ABORT: non-empty sqlite tables not in ORM metadata:", missing)
        print("non-empty sqlite tables:", nonempty)
        return 3

    print("Non-empty source tables:", nonempty)
    if args.dry_run:
        print("dry-run: nothing written")
        return 0

    copied = {}
    with src.connect() as s, dst.begin() as d:
        # The destination schema (built by alembic) may carry seed rows
        # (e.g. a default jwt secret). Make SQLite authoritative: wipe all
        # mapped tables first so secrets/tokens stay identical post-cutover.
        names = ", ".join(f'"{t.name}"' for t in meta.sorted_tables)
        if names:
            d.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))

        for table in meta.sorted_tables:
            if table.name not in sqlite_tables:
                continue
            rows = [dict(r) for r in s.execute(select(table)).mappings().all()]
            if not rows:
                continue
            d.execute(table.insert(), rows)
            copied[table.name] = len(rows)

        # Re-align PostgreSQL serial sequences for 'id' PKs.
        for table in meta.sorted_tables:
            if "id" not in table.columns:
                continue
            seq = d.execute(
                text("SELECT pg_get_serial_sequence(:t, 'id')"),
                {"t": table.name},
            ).scalar()
            if not seq:
                continue
            d.execute(
                text(
                    f"SELECT setval('{seq}', "
                    f"COALESCE((SELECT MAX(id) FROM \"{table.name}\"), 1), "
                    f"(SELECT MAX(id) FROM \"{table.name}\") IS NOT NULL)"
                )
            )

    print("Copied rows per table:")
    for name, n in copied.items():
        print(f"  {name}: {n}")
    print("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
