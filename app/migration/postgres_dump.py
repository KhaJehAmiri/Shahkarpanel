"""Parse 3x-ui PostgreSQL custom backups (pg_dump -Fc, magic PGDMP)."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from app.migration.sqlite_dump import _PanelTableAccess, load_panel_from_tables

logger = logging.getLogger("shahkar-migration-3xui")

PGDMP_MAGIC = b"PGDMP"


def is_pg_custom_dump(path: Path) -> bool:
    try:
        return path.read_bytes()[:5] == PGDMP_MAGIC
    except OSError:
        return False


def _repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _compose_file() -> str:
    root = _repo_root()
    for name in ("docker-compose.postgres.yml", "docker-compose.yml"):
        if os.path.isfile(os.path.join(root, name)):
            return name
    raise RuntimeError("docker-compose.postgres.yml not found — cannot restore PostgreSQL backup")


def _compose_cmd(*args: str) -> list[str]:
    project = os.environ.get("COMPOSE_PROJECT_NAME", "shahkar").strip() or "shahkar"
    compose_file = _compose_file()
    return [
        "docker",
        "compose",
        "-p",
        project,
        "-f",
        compose_file,
        *args,
    ]


def _pg_credentials() -> tuple[str, str, int, dict[str, str]]:
    from app.db.base import IS_POSTGRESQL, engine

    if not IS_POSTGRESQL:
        raise ValueError(
            "This backup is a PostgreSQL pg_dump file. "
            "Import it only when Shahkar itself uses PostgreSQL."
        )
    url = engine.url
    user = str(url.username or "shahkar")
    host = str(url.host or "127.0.0.1")
    port = int(url.port or 5432)
    env = os.environ.copy()
    if url.password:
        env["PGPASSWORD"] = str(url.password)
    return user, host, port, env


def _run_psql(db_name: str, sql: str, *, user: str, host: str, port: int, env: dict[str, str]) -> None:
    cmd = ["psql", "-h", host, "-p", str(port), "-U", user, "-d", db_name, "-v", "ON_ERROR_STOP=1", "-c", sql]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(detail or f"psql failed for database {db_name}")


def _connect_temp_db(db_name: str):
    import psycopg2

    from app.db.base import engine

    url = engine.url
    return psycopg2.connect(
        host=url.host or "127.0.0.1",
        port=int(url.port or 5432),
        user=str(url.username or "shahkar"),
        password=str(url.password or ""),
        dbname=db_name,
    )


class _PostgresPanelTables(_PanelTableAccess):
    def __init__(self, conn) -> None:
        self._conn = conn

    def table_exists(self, name: str) -> bool:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = %s LIMIT 1",
                (name,),
            )
            return cur.fetchone() is not None

    def rows(self, table: str) -> list[dict[str, Any]]:
        if not self.table_exists(table):
            return []
        with self._conn.cursor() as cur:
            cur.execute(f'SELECT * FROM "{table}"')
            cols = [desc[0] for desc in cur.description or []]
            return [{cols[i]: row[i] for i in range(len(cols))} for row in cur.fetchall()]


def _restore_to_temp_db(
    path: Path,
    tmp_db: str,
    *,
    user: str,
    host: str,
    port: int,
    env: dict[str, str],
) -> None:
    _run_psql("postgres", f"CREATE DATABASE {tmp_db};", user=user, host=host, port=port, env=env)
    cmd = [
        "pg_restore",
        "-h",
        host,
        "-p",
        str(port),
        "-U",
        user,
        "-d",
        tmp_db,
        "--no-owner",
        "--no-privileges",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)
    if proc.returncode != 0:
        probe = subprocess.run(
            ["psql", "-h", host, "-p", str(port), "-U", user, "-d", tmp_db, "-c", "\\dt inbounds"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        if probe.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(detail or f"pg_restore failed for {path.name}")


def _drop_temp_db(tmp_db: str, *, user: str, host: str, port: int, env: dict[str, str]) -> None:
    try:
        _run_psql("postgres", f"DROP DATABASE IF EXISTS {tmp_db};", user=user, host=host, port=port, env=env)
    except RuntimeError as exc:
        logger.warning("Could not drop temporary migration database %s: %s", tmp_db, exc)


def _load_from_temp_db(tmp_db: str, path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    conn = _connect_temp_db(tmp_db)
    try:
        settings, inbounds, panel_obj = load_panel_from_tables(_PostgresPanelTables(conn))
        panel_obj["source"] = "3x-ui-postgres"
        panel_obj["backup_path"] = str(path)
        return settings, inbounds, panel_obj
    finally:
        conn.close()


def _load_via_local_pg_tools(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    if not shutil.which("pg_restore") or not shutil.which("psql"):
        raise RuntimeError("pg_restore/psql not installed in panel container")
    user, host, port, env = _pg_credentials()
    tmp_db = f"shahkar_mig_{uuid.uuid4().hex[:12]}"
    try:
        _restore_to_temp_db(path, tmp_db, user=user, host=host, port=port, env=env)
        return _load_from_temp_db(tmp_db, path)
    finally:
        _drop_temp_db(tmp_db, user=user, host=host, port=port, env=env)


def _postgres_exec(*pg_args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    cmd = _compose_cmd("exec", "-T", "postgres", *pg_args)
    return subprocess.run(
        cmd,
        cwd=_repo_root(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _load_via_docker_compose(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    user, _, _, env = _pg_credentials()
    tmp_db = f"shahkar_mig_{uuid.uuid4().hex[:12]}"
    remote_path = f"/tmp/{tmp_db}.dump"

    try:
        cp = subprocess.run(
            _compose_cmd("cp", str(path), f"postgres:{remote_path}"),
            cwd=_repo_root(),
            capture_output=True,
            text=True,
            check=False,
        )
        if cp.returncode != 0:
            raise RuntimeError(
                f"Could not copy backup into postgres container: {cp.stderr.strip() or cp.stdout.strip()}"
            )

        created = _postgres_exec("psql", "-U", user, "-d", "postgres", "-c", f"CREATE DATABASE {tmp_db};", env=env)
        if created.returncode != 0:
            raise RuntimeError(
                f"Could not create temporary import database: {created.stderr.strip() or created.stdout.strip()}"
            )

        restored = _postgres_exec(
            "pg_restore",
            "-U",
            user,
            "-d",
            tmp_db,
            "--no-owner",
            "--no-privileges",
            remote_path,
            env=env,
        )
        if restored.returncode != 0:
            probe = _postgres_exec("psql", "-U", user, "-d", tmp_db, "-c", "\\dt inbounds", env=env)
            if probe.returncode != 0:
                raise RuntimeError(
                    f"pg_restore failed for {path.name}: {restored.stderr.strip() or restored.stdout.strip()}"
                )

        return _load_from_temp_db(tmp_db, path)
    finally:
        _postgres_exec("psql", "-U", user, "-d", "postgres", "-c", f"DROP DATABASE IF EXISTS {tmp_db};", env=env)
        _postgres_exec("rm", "-f", remote_path, env=env)


def load_panel_from_postgres_dump(path: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Restore a 3x-ui pg_dump custom-format backup into a temp DB and read panel data."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(str(p))
    if not is_pg_custom_dump(p):
        raise ValueError(f"Not a PostgreSQL custom dump: {p.name}")

    if shutil.which("pg_restore") and shutil.which("psql"):
        return _load_via_local_pg_tools(p)

    if shutil.which("docker"):
        return _load_via_docker_compose(p)

    raise RuntimeError(
        "PostgreSQL pg_dump import requires pg_restore/psql in the panel container "
        "or docker access to the postgres service."
    )


def pg_dump_format_hint(path: Path) -> str:
    return (
        f"{path.name} is a PostgreSQL pg_dump backup (not SQLite). "
        "Shahkar will import it via pg_restore automatically."
    )
