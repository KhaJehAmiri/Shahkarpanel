"""Backup & disaster recovery.

Produces a single ``.tar.gz`` archive containing everything needed to restore a
NexusPanel: the database, the Xray config, the TLS material stored in the
database and (optionally) the ``.env`` file.

Supported databases:
- SQLite    : the database file is copied verbatim (and can be restored here).
- PostgreSQL: dumped with ``pg_dump`` when available.
- MySQL     : dumped with ``mysqldump`` when available.
"""
import logging
import os
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime
from typing import List, Optional

from config import (
    BACKUP_DIR,
    BACKUP_INCLUDE_ENV,
    BACKUP_RETENTION_COUNT,
    XRAY_JSON,
)

logger = logging.getLogger("uvicorn.error")

ARCHIVE_PREFIX = "nexuspanel-backup-"


def _ensure_dir() -> None:
    # Backups hold the DB dump and TLS private key — keep the dir owner-only.
    os.makedirs(BACKUP_DIR, mode=0o700, exist_ok=True)
    try:
        os.chmod(BACKUP_DIR, 0o700)
    except OSError:
        pass


def _compose_pg_dump_cmd(url) -> Optional[List[str]]:
    """Run pg_dump via the postgres service container when CLI is not in the panel image."""
    if not shutil.which("docker"):
        return None
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    compose_file = None
    for name in ("docker-compose.postgres.yml", "docker-compose.yml"):
        path = os.path.join(root, name)
        if os.path.isfile(path):
            compose_file = name
            break
    if not compose_file:
        return None
    project = os.environ.get("COMPOSE_PROJECT_NAME", "nexuspanel").strip() or "nexuspanel"
    cmd = [
        "docker", "compose", "-p", project, "-f", compose_file,
        "exec", "-T", "postgres",
        "pg_dump", "--no-owner", "--no-privileges",
    ]
    if url.username:
        cmd += ["-U", str(url.username)]
    cmd += ["-d", url.database]
    return cmd


def _dump_database(workdir: str) -> None:
    from app.db.base import engine

    url = engine.url
    name = engine.dialect.name

    if name == "sqlite":
        db_path = url.database
        if db_path and os.path.isfile(db_path):
            shutil.copy2(db_path, os.path.join(workdir, "db.sqlite3"))
        return

    if name == "postgresql":
        env = os.environ.copy()
        if url.password:
            env["PGPASSWORD"] = str(url.password)
        out_path = os.path.join(workdir, "db.sql")
        if shutil.which("pg_dump"):
            cmd = ["pg_dump", "--no-owner", "--no-privileges"]
            if url.host:
                cmd += ["-h", str(url.host)]
            if url.port:
                cmd += ["-p", str(url.port)]
            if url.username:
                cmd += ["-U", str(url.username)]
            cmd += ["-d", url.database]
            with open(out_path, "wb") as out:
                subprocess.run(cmd, check=True, stdout=out, env=env)
            return
        docker_cmd = _compose_pg_dump_cmd(url)
        if docker_cmd:
            with open(out_path, "wb") as out:
                subprocess.run(
                    docker_cmd, check=True, stdout=out, env=env,
                    cwd=os.path.join(os.path.dirname(__file__), ".."),
                )
            return
        logger.warning("Backup: pg_dump unavailable; skipping DB dump")
        return

    if name == "mysql":
        cmd = ["mysqldump", "--single-transaction"]
        if url.host:
            cmd += ["-h", str(url.host)]
        if url.port:
            cmd += ["-P", str(url.port)]
        if url.username:
            cmd += ["-u", str(url.username)]
        if url.password:
            cmd += [f"-p{url.password}"]
        cmd += [url.database]
        with open(os.path.join(workdir, "db.sql"), "wb") as out:
            subprocess.run(cmd, check=True, stdout=out)
        return

    logger.warning("Backup: unsupported database dialect '%s'; skipping DB dump", name)


def _dump_tls(workdir: str) -> None:
    try:
        from app.db import GetDB, get_tls_certificate

        with GetDB() as db:
            tls = get_tls_certificate(db)
            if tls:
                with open(os.path.join(workdir, "ssl_cert.pem"), "w") as f:
                    f.write(tls.certificate)
                with open(os.path.join(workdir, "ssl_key.pem"), "w") as f:
                    f.write(tls.key)
    except Exception:
        logger.exception("Backup: failed to export TLS material")


def create_backup() -> str:
    """Create a backup archive and return its absolute path."""
    _ensure_dir()
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    archive_path = os.path.join(BACKUP_DIR, f"{ARCHIVE_PREFIX}{timestamp}.tar.gz")

    with tempfile.TemporaryDirectory() as workdir:
        _dump_database(workdir)
        _dump_tls(workdir)

        if XRAY_JSON and os.path.isfile(XRAY_JSON):
            shutil.copy2(XRAY_JSON, os.path.join(workdir, "xray_config.json"))

        if BACKUP_INCLUDE_ENV:
            env_path = os.environ.get("DOTENV_PATH", ".env")
            if os.path.isfile(env_path) and os.access(env_path, os.R_OK):
                shutil.copy2(env_path, os.path.join(workdir, "env.backup"))

        with tarfile.open(archive_path, "w:gz") as tar:
            for entry in os.listdir(workdir):
                tar.add(os.path.join(workdir, entry), arcname=entry)

    # The archive contains the DB dump and TLS private key — restrict to owner.
    try:
        os.chmod(archive_path, 0o600)
    except OSError:
        pass

    logger.info("Backup created: %s", archive_path)
    prune_backups()
    return archive_path


def list_backups() -> List[str]:
    if not os.path.isdir(BACKUP_DIR):
        return []
    files = [
        os.path.join(BACKUP_DIR, f)
        for f in os.listdir(BACKUP_DIR)
        if f.startswith(ARCHIVE_PREFIX) and f.endswith(".tar.gz")
    ]
    return sorted(files)


def prune_backups(keep: Optional[int] = None) -> int:
    keep = BACKUP_RETENTION_COUNT if keep is None else keep
    if keep <= 0:
        return 0
    backups = list_backups()
    to_delete = backups[:-keep] if len(backups) > keep else []
    for path in to_delete:
        try:
            os.remove(path)
        except OSError:
            pass
    return len(to_delete)


def restore_backup(archive_path: str) -> None:
    """Restore a backup archive.

    For SQLite this replaces the live database file, the Xray config and TLS
    files. For PostgreSQL/MySQL the SQL dump is extracted next to the archive
    and must be imported manually (psql / mysql), since restoring a live server
    requires operator confirmation. This operation is destructive.
    """
    from app.db.base import engine

    if not os.path.isfile(archive_path):
        raise FileNotFoundError(archive_path)

    with tempfile.TemporaryDirectory() as workdir:
        with tarfile.open(archive_path, "r:gz") as tar:
            # Reject path traversal in archives (CVE-class tar slip).
            for member in tar.getmembers():
                dest = os.path.normpath(os.path.join(workdir, member.name))
                if not dest.startswith(os.path.abspath(workdir) + os.sep) and dest != os.path.abspath(workdir):
                    raise ValueError(f"Unsafe path in backup archive: {member.name}")
            tar.extractall(workdir, filter="data")

        name = engine.dialect.name
        if name == "sqlite":
            src = os.path.join(workdir, "db.sqlite3")
            if os.path.isfile(src) and engine.url.database:
                shutil.copy2(src, engine.url.database)

            xray_src = os.path.join(workdir, "xray_config.json")
            if os.path.isfile(xray_src) and XRAY_JSON:
                shutil.copy2(xray_src, XRAY_JSON)

            logger.info("SQLite backup restored from %s", archive_path)
        else:
            sql_src = os.path.join(workdir, "db.sql")
            dest = os.path.join(BACKUP_DIR, "restore-db.sql")
            if os.path.isfile(sql_src):
                shutil.copy2(sql_src, dest)
            raise RuntimeError(
                f"Automatic restore is only supported for SQLite. The SQL dump "
                f"has been extracted to {dest}; import it manually into your "
                f"{name} database."
            )
