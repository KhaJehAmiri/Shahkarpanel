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
import threading
from datetime import datetime
from typing import List, Optional
from uuid import uuid4

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
        "pg_dump", "--no-owner", "--no-privileges", "--clean", "--if-exists",
    ]
    if url.username:
        cmd += ["-U", str(url.username)]
    cmd += ["-d", url.database]
    return cmd


def _compose_psql_cmd(username: str) -> Optional[List[str]]:
    """psql through the compose postgres service (local socket, no password).

    In compose deployments the bootstrap role (``POSTGRES_USER``, same as the
    app user) is the superuser, which lets restore terminate the panel's own DB
    sessions and temporarily block new connections — without that, live
    sessions hold locks that deadlock the dump's DROP/CREATE statements.
    """
    if not shutil.which("docker"):
        return None
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    compose_file = None
    for name in ("docker-compose.postgres.yml", "docker-compose.yml"):
        if os.path.isfile(os.path.join(root, name)):
            compose_file = name
            break
    if not compose_file:
        return None
    project = os.environ.get("COMPOSE_PROJECT_NAME", "nexuspanel").strip() or "nexuspanel"
    return [
        "docker", "compose", "-p", project, "-f", compose_file,
        "exec", "-T", "postgres",
        "psql", "-U", username,
    ]


# Session parameters emitted by newer pg_dump clients that older servers
# reject (e.g. pg_dump 17 emits transaction_timeout, unknown to PG 16). With
# ON_ERROR_STOP they would abort the whole import, so strip them.
_PG_DUMP_SET_SKIP = (b"SET transaction_timeout",)


def _sanitize_pg_dump(path: str) -> None:
    tmp = path + ".sanitized"
    with open(path, "rb") as src, open(tmp, "wb") as out:
        for line in src:
            if line.startswith(_PG_DUMP_SET_SKIP):
                continue
            out.write(line)
    os.replace(tmp, path)


def _restore_postgres_dump(sql_src: str) -> None:
    from app.db.base import engine

    url = engine.url
    dbname = str(url.database)
    appuser = str(url.username or "postgres")

    _sanitize_pg_dump(sql_src)

    app_name = "nexuspanel-restore"
    # Block new connections from non-superuser roles and kick everyone else
    # off. When the app role IS the superuser (compose bootstrap role) the
    # limit doesn't apply to it, so a watchdog below keeps terminating any
    # session that reconnects while the import runs.
    quiesce = (
        f'ALTER DATABASE "{dbname}" CONNECTION LIMIT 0; '
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = '{dbname}' AND pid <> pg_backend_pid();"
    )
    # Recreating the schema makes restore deterministic: everything is rebuilt
    # from the dump, and legacy dumps taken without --clean import fine too.
    reset_schema = "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;"
    release = f'ALTER DATABASE "{dbname}" CONNECTION LIMIT -1;'
    terminate_others = (
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = '{dbname}' AND application_name <> '{app_name}';"
    )

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    compose_cmd = _compose_psql_cmd(appuser)

    env = os.environ.copy()
    env["PGAPPNAME"] = app_name
    if url.password:
        env["PGPASSWORD"] = str(url.password)

    def _psql(*args: str, dbname_override: Optional[str] = None, **kwargs):
        target = dbname_override or dbname
        if compose_cmd:
            # compose exec needs -e to forward the app-name marker into the
            # postgres container.
            base = compose_cmd[:]
            base.insert(base.index("exec") + 1, "-e")
            base.insert(base.index("exec") + 2, f"PGAPPNAME={app_name}")
            cmd = base + ["-d", target, *args]
            return subprocess.run(cmd, cwd=root, env=env, **kwargs)
        cmd = [
            "psql",
            "-h", str(url.host or "localhost"),
            "-p", str(url.port or 5432),
            "-U", appuser,
            "-d", target,
            *args,
        ]
        return subprocess.run(cmd, env=env, **kwargs)

    if not compose_cmd and not shutil.which("psql"):
        raise RuntimeError(
            "PostgreSQL restore requires either docker compose access to the "
            "postgres service or a local psql CLI."
        )

    # Drop pooled connections so the panel's own sessions can't block the DDL.
    engine.dispose()

    # Long-lived app sessions (SSE streams, jobs) hold locks that would stall
    # DROP SCHEMA forever; keep terminating them until the import finishes. The
    # watchdog talks to the maintenance DB so it is never blocked itself.
    stop = threading.Event()

    def _watchdog() -> None:
        while not stop.wait(2.0):
            _psql(
                "-c", terminate_others, dbname_override="postgres",
                check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )

    watchdog = threading.Thread(target=_watchdog, name="pg-restore-watchdog", daemon=True)
    watchdog.start()
    try:
        if compose_cmd:
            with open(sql_src, "rb") as sql_file:
                proc = _psql(
                    "-v", "ON_ERROR_STOP=1",
                    "-c", quiesce,
                    "-c", reset_schema,
                    "-f", "/dev/stdin",
                    "-c", release,
                    input=sql_file.read(),
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                )
        else:
            proc = _psql(
                "-v", "ON_ERROR_STOP=1",
                "-c", quiesce,
                "-c", reset_schema,
                "-f", sql_src,
                "-c", release,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )
        if proc.returncode != 0:
            tail = (proc.stderr or b"").decode(errors="replace")[-800:]
            raise RuntimeError(f"PostgreSQL restore failed: {tail.strip()}")
    finally:
        stop.set()
        watchdog.join(timeout=10)
        # Always lift the connection limit, even when the import failed.
        _psql(
            "-c", release, dbname_override="postgres",
            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        engine.dispose()


def _schedule_panel_restart() -> None:
    """Restart the panel (best-effort, detached) so it reloads the restored DB
    state and Xray config instead of serving stale in-memory caches.

    Must be a single atomic ``docker restart``: it runs inside the very
    container being restarted, so a ``stop && start`` sequence dies after the
    stop and the panel would stay down.
    """
    try:
        from app.system.update_jobs import _own_container_id, _restart_panel

        cid = _own_container_id() if shutil.which("docker") else None
        if cid:
            subprocess.Popen(
                ["sh", "-c", f"sleep 1; docker restart -t 3 {cid}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        else:
            _restart_panel(None)
        logger.info("Restore: panel restart scheduled")
    except Exception:
        logger.warning(
            "Restore: could not schedule a panel restart; restart it manually "
            "to fully apply the restored backup."
        )


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
            # --clean --if-exists lets the dump be re-imported over an existing
            # database (drops objects first), which is what makes restore work.
            cmd = ["pg_dump", "--no-owner", "--no-privileges", "--clean", "--if-exists"]
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
            from app.runtime_env import RUNTIME_ENV_PATH

            env_path = os.environ.get("DOTENV_PATH", ".env")
            if os.path.isfile(env_path) and os.access(env_path, os.R_OK):
                shutil.copy2(env_path, os.path.join(workdir, "env.backup"))
            runtime_path = str(RUNTIME_ENV_PATH)
            if os.path.isfile(runtime_path) and os.access(runtime_path, os.R_OK):
                shutil.copy2(runtime_path, os.path.join(workdir, "runtime-env.backup"))

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


def _is_valid_archive(path: str) -> bool:
    """A NexusPanel backup is a gzip tar that contains a DB dump (and, for
    older archives, at least the Xray config). Reject anything else early so a
    bad upload can't be "restored"."""
    try:
        with tarfile.open(path, "r:gz") as tar:
            names = tar.getnames()
    except (tarfile.TarError, OSError, EOFError):
        return False
    known = {"db.sqlite3", "db.sql", "xray_config.json"}
    return any(os.path.basename(n) in known for n in names)


def save_uploaded_backup(content: bytes, original_name: str = "") -> str:
    """Persist an uploaded backup archive into ``BACKUP_DIR`` under a managed
    name so it shows up in :func:`list_backups` and can be restored. Returns the
    stored filename.

    Raises ``ValueError`` when the upload is not a valid NexusPanel archive.
    """
    _ensure_dir()
    # uuid suffix: second-resolution timestamps collide when uploads arrive in
    # the same second, letting a bad upload overwrite (and on failed validation
    # delete) a valid one.
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    filename = f"{ARCHIVE_PREFIX}upload-{timestamp}-{uuid4().hex[:8]}.tar.gz"
    dest = os.path.join(BACKUP_DIR, filename)
    with open(dest, "wb") as f:
        f.write(content)
    try:
        os.chmod(dest, 0o600)
    except OSError:
        pass
    if not _is_valid_archive(dest):
        try:
            os.remove(dest)
        except OSError:
            pass
        raise ValueError(
            "Uploaded file is not a valid NexusPanel backup archive "
            "(expected a .tar.gz containing db.sqlite3 or db.sql)."
        )
    logger.info("Backup uploaded: %s", dest)
    prune_backups()
    return filename


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


def restore_backup(archive_path: str, restart_panel: bool = True) -> None:
    """Restore a backup archive. This operation is destructive.

    SQLite: the live database file and Xray config are replaced. PostgreSQL:
    other connections are terminated, the schema is recreated and the dump
    imported. MySQL: the dump is piped into the mysql CLI. Afterwards a panel
    restart is scheduled (unless ``restart_panel`` is False) so no stale
    in-memory state survives the restore.
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
            if not os.path.isfile(src):
                raise RuntimeError("Backup archive contains no db.sqlite3")
            if engine.url.database:
                engine.dispose()
                shutil.copy2(src, engine.url.database)

            xray_src = os.path.join(workdir, "xray_config.json")
            if os.path.isfile(xray_src) and XRAY_JSON:
                shutil.copy2(xray_src, XRAY_JSON)

            logger.info("SQLite backup restored from %s", archive_path)
            if restart_panel:
                _schedule_panel_restart()
            return

        sql_src = os.path.join(workdir, "db.sql")
        if not os.path.isfile(sql_src):
            raise RuntimeError("Backup archive contains no db.sql dump")

        xray_src = os.path.join(workdir, "xray_config.json")
        if os.path.isfile(xray_src) and XRAY_JSON:
            shutil.copy2(xray_src, XRAY_JSON)

        if name == "postgresql":
            _restore_postgres_dump(sql_src)
            logger.info("PostgreSQL backup restored from %s", archive_path)
            if restart_panel:
                _schedule_panel_restart()
            return

        if name == "mysql" and shutil.which("mysql"):
            url = engine.url
            cmd = [
                "mysql",
                "-h",
                url.host or "localhost",
                "-P",
                str(url.port or 3306),
                "-u",
                str(url.username or "root"),
                str(url.database),
            ]
            env = os.environ.copy()
            if url.password:
                env["MYSQL_PWD"] = str(url.password)
            engine.dispose()
            with open(sql_src, "rb") as sql_file:
                subprocess.run(cmd, input=sql_file.read(), check=True, env=env)
            logger.info("MySQL backup restored from %s", archive_path)
            if restart_panel:
                _schedule_panel_restart()
            return

        dest = os.path.join(BACKUP_DIR, "restore-db.sql")
        shutil.copy2(sql_src, dest)
        raise RuntimeError(
            f"Automatic restore for {name} requires the mysql CLI. The SQL dump "
            f"has been extracted to {dest}; import it manually."
        )
