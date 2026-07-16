"""Backup & restore — 3x-ui style.

Simple, fail-hard database backup/restore:

- **Download** writes a migration ``.tar.gz`` (DB + TLS + node control secrets)
  so restoring onto a new server keeps panel↔node auth working.
- **Restore** accepts that bundle (or a bare ``.dump`` / ``.db`` / legacy tar),
  merges control secrets, clears node cert pins, replaces the live database,
  then restarts the panel.

Scheduled jobs keep DB copies under ``BACKUP_DIR``.
Never create an "empty" backup that skipped the database.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import socket
import subprocess
import tarfile
import tempfile
import threading
from datetime import datetime
from typing import List, Optional, Tuple
from uuid import uuid4

from config import (
    BACKUP_DIR,
    BACKUP_INCLUDE_ENV,
    BACKUP_RETENTION_COUNT,
    XRAY_JSON,
)

logger = logging.getLogger("uvicorn.error")

ARCHIVE_PREFIX = "nexuspanel-backup-"
_SQLITE_MAGIC = b"SQLite format 3"
_PG_CUSTOM_MAGIC = b"PGDMP"
_GZIP_MAGIC = b"\x1f\x8b"


def _ensure_dir() -> None:
    os.makedirs(BACKUP_DIR, mode=0o700, exist_ok=True)
    try:
        os.chmod(BACKUP_DIR, 0o700)
    except OSError:
        pass


def _db_backend() -> str:
    from app.db.base import engine

    return engine.dialect.name


def _safe_host_label() -> str:
    host = (socket.gethostname() or "nexuspanel").strip().lower()
    host = re.sub(r"[^a-z0-9._-]+", "-", host).strip("-._") or "nexuspanel"
    return host[:64]


def download_name(*, backend: Optional[str] = None, migration: bool = False) -> str:
    """3x-ui style filename: ``{host}_YYYY-MM-DD_HHMMSS.{db|dump|sql|tar.gz}``."""
    stamp = datetime.utcnow().strftime("%Y-%m-%d_%H%M%S")
    if migration:
        return f"{_safe_host_label()}_{stamp}.tar.gz"
    name = backend or _db_backend()
    if name == "sqlite":
        ext = "db"
    elif name == "postgresql":
        ext = "dump"
    else:
        ext = "sql"
    return f"{_safe_host_label()}_{stamp}.{ext}"


# Keys restored onto a new panel so existing node agents keep accepting us.
_CONTROL_ENV_KEYS = ("NODE_CONTROL_SECRET", "NODE_BOOTSTRAP_TOKEN")


def _parse_env_file(path: str) -> dict:
    out: dict = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip("'").strip('"')
                if key:
                    out[key] = val
    except OSError:
        pass
    return out


def _write_control_env_backup(workdir: str) -> None:
    """Write ``runtime-env.backup`` with node-control secrets for migration."""
    from app.runtime_env import RUNTIME_ENV_PATH

    values: dict = {}
    for path in (
        str(RUNTIME_ENV_PATH),
        os.environ.get("DOTENV_PATH", ".env"),
        ".env",
    ):
        if path and os.path.isfile(path) and os.access(path, os.R_OK):
            parsed = _parse_env_file(path)
            for key in _CONTROL_ENV_KEYS:
                if key in parsed and parsed[key] and key not in values:
                    values[key] = parsed[key]
    for key in _CONTROL_ENV_KEYS:
        env_val = os.environ.get(key, "").strip()
        if env_val and key not in values:
            values[key] = env_val
    if not values:
        return
    dest = os.path.join(workdir, "runtime-env.backup")
    lines = [
        "# NexusPanel migration control secrets — do not commit",
        *(f"{k}={values[k]}" for k in _CONTROL_ENV_KEYS if k in values),
        "",
    ]
    with open(dest, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    try:
        os.chmod(dest, 0o600)
    except OSError:
        pass


def _merge_control_secrets_from_backup(workdir: str) -> None:
    """Merge NODE_CONTROL_SECRET / NODE_BOOTSTRAP_TOKEN into runtime .env."""
    from app.runtime_env import RUNTIME_ENV_PATH

    candidates = [
        os.path.join(workdir, "runtime-env.backup"),
        os.path.join(workdir, "env.backup"),
    ]
    incoming: dict = {}
    for path in candidates:
        if not os.path.isfile(path):
            continue
        parsed = _parse_env_file(path)
        for key in _CONTROL_ENV_KEYS:
            if parsed.get(key) and key not in incoming:
                incoming[key] = parsed[key]
    if not incoming:
        return

    runtime = RUNTIME_ENV_PATH
    runtime.parent.mkdir(parents=True, exist_ok=True)
    existing = _parse_env_file(str(runtime)) if runtime.is_file() else {}
    existing.update(incoming)
    body = (
        f"# Runtime secrets — outside git checkout ({runtime})\n"
        + "\n".join(f"{k}={v}" for k, v in sorted(existing.items()))
        + "\n"
    )
    runtime.write_text(body, encoding="utf-8")
    try:
        os.chmod(runtime, 0o600)
    except OSError:
        pass
    for key, val in incoming.items():
        os.environ[key] = val
    logger.info(
        "Restore: merged control secrets into %s (%s)",
        runtime,
        ", ".join(sorted(incoming)),
    )


def _clear_all_node_cert_pins() -> None:
    """Clear TOFU pins so nodes re-pin after a panel move / cert change."""
    try:
        from app.db import GetDB
        from app.db.models import Node

        with GetDB() as db:
            updated = (
                db.query(Node)
                .filter(Node.server_cert_sha256.isnot(None))
                .update({Node.server_cert_sha256: None}, synchronize_session=False)
            )
            db.commit()
        if updated:
            logger.info("Restore: cleared TLS cert pins on %s node(s)", updated)
    except Exception:
        logger.warning("Restore: could not clear node cert pins", exc_info=True)


def _post_restore_prepare(*, workdir: Optional[str] = None) -> None:
    if workdir:
        _merge_control_secrets_from_backup(workdir)
    _clear_all_node_cert_pins()


def _compose_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _compose_file() -> Optional[str]:
    root = _compose_root()
    for name in ("docker-compose.postgres.yml", "docker-compose.yml"):
        if os.path.isfile(os.path.join(root, name)):
            return name
    return None


def _compose_pg_cmd(tool: str, *extra: str) -> Optional[List[str]]:
    """Run ``pg_dump`` / ``pg_restore`` / ``psql`` inside the compose postgres service."""
    if not shutil.which("docker"):
        return None
    compose_file = _compose_file()
    if not compose_file:
        return None
    from app.db.base import engine

    url = engine.url
    project = os.environ.get("COMPOSE_PROJECT_NAME", "nexuspanel").strip() or "nexuspanel"
    cmd = [
        "docker", "compose", "-p", project, "-f", compose_file,
        "exec", "-T", "postgres",
        tool,
    ]
    if url.username:
        cmd += ["-U", str(url.username)]
    cmd.extend(extra)
    return cmd


def _pg_env() -> dict:
    from app.db.base import engine

    url = engine.url
    env = os.environ.copy()
    if url.password:
        env["PGPASSWORD"] = str(url.password)
    return env


def _chmod_owner_only(path: str) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def _sqlite_checkpoint() -> None:
    """Flush WAL so a file copy is consistent (same idea as 3x-ui Checkpoint)."""
    from app.db.base import engine

    if engine.dialect.name != "sqlite":
        return
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        logger.warning("Backup: SQLite checkpoint failed; copying DB as-is", exc_info=True)


def _export_sqlite(dest: str) -> None:
    from app.db.base import engine

    db_path = engine.url.database
    if not db_path or not os.path.isfile(db_path):
        raise RuntimeError("SQLite database file not found")
    _sqlite_checkpoint()
    shutil.copy2(db_path, dest)
    if not os.path.isfile(dest) or os.path.getsize(dest) < 100:
        raise RuntimeError("SQLite backup copy is empty or missing")


def _export_postgres_custom(dest: str) -> None:
    """PostgreSQL custom-format dump (``pg_dump -Fc``) — same as 3x-ui.

    Prefer the compose postgres service's ``pg_dump`` so the dump format
    matches the server major version (a newer client on the panel image can
    emit SET options / archive versions the server cannot restore).
    """
    from app.db.base import engine

    url = engine.url
    env = _pg_env()
    errors: List[str] = []

    def _run(cmd: List[str], *, cwd: Optional[str] = None) -> None:
        with open(dest, "wb") as out:
            proc = subprocess.run(
                cmd, stdout=out, stderr=subprocess.PIPE, env=env, cwd=cwd,
            )
        if proc.returncode != 0:
            # Don't leave a partial/corrupt dump behind.
            try:
                os.remove(dest)
            except OSError:
                pass
            msg = (proc.stderr or b"").decode(errors="replace")[-800:].strip()
            errors.append(msg or f"exit {proc.returncode}")
            raise RuntimeError("pg_dump failed")

    docker_cmd = _compose_pg_cmd(
        "pg_dump",
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "-d", str(url.database),
    )
    if docker_cmd:
        try:
            _run(docker_cmd, cwd=_compose_root())
            return
        except RuntimeError:
            logger.warning(
                "Backup: compose pg_dump failed (%s); trying local client",
                errors[-1] if errors else "",
            )

    if shutil.which("pg_dump"):
        cmd = [
            "pg_dump",
            "--format=custom",
            "--no-owner",
            "--no-privileges",
        ]
        if url.host:
            cmd += ["-h", str(url.host)]
        if url.port:
            cmd += ["-p", str(url.port)]
        if url.username:
            cmd += ["-U", str(url.username)]
        cmd += ["-d", str(url.database)]
        try:
            _run(cmd)
            return
        except RuntimeError:
            pass

    detail = (errors[-1] if errors else "").strip()
    raise RuntimeError(
        "PostgreSQL backup failed: pg_dump unavailable or errored"
        + (f": {detail}" if detail else "")
    )


def _export_mysql(dest: str) -> None:
    from app.db.base import engine

    url = engine.url
    if not shutil.which("mysqldump"):
        raise RuntimeError("mysqldump not found; cannot back up MySQL")
    cmd = ["mysqldump", "--single-transaction", "--routines", "--triggers"]
    if url.host:
        cmd += ["-h", str(url.host)]
    if url.port:
        cmd += ["-P", str(url.port)]
    if url.username:
        cmd += ["-u", str(url.username)]
    if url.password:
        cmd += [f"-p{url.password}"]
    cmd += [str(url.database)]
    with open(dest, "wb") as out:
        proc = subprocess.run(cmd, stdout=out, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        tail = (proc.stderr or b"").decode(errors="replace")[-800:]
        raise RuntimeError(f"mysqldump failed: {tail.strip()}")


def _dump_database_to(dest: str, backend: Optional[str] = None) -> str:
    """Write the DB dump to ``dest``. Returns the backend name used."""
    name = backend or _db_backend()
    if name == "sqlite":
        _export_sqlite(dest)
    elif name == "postgresql":
        _export_postgres_custom(dest)
    elif name == "mysql":
        _export_mysql(dest)
    else:
        raise RuntimeError(f"Unsupported database dialect: {name}")
    if not os.path.isfile(dest) or os.path.getsize(dest) < 16:
        raise RuntimeError("Database dump is empty")
    return name


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
    """Create a managed backup under ``BACKUP_DIR`` and return its absolute path.

    Primary artifact is the DB file (``.db`` / ``.dump``). A companion
    ``.tar.gz`` with TLS + Xray config is only written when those extras exist
    and ``BACKUP_INCLUDE_ENV`` (or TLS/Xray) warrants a full bundle — for
    scheduled jobs we always keep the DB file so restore stays 3x-ui-simple.
    """
    _ensure_dir()
    backend = _db_backend()
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    if backend == "sqlite":
        ext = "db"
    elif backend == "postgresql":
        ext = "dump"
    else:
        ext = "sql"
    archive_path = os.path.join(BACKUP_DIR, f"{ARCHIVE_PREFIX}{stamp}.{ext}")
    _dump_database_to(archive_path, backend)
    _chmod_owner_only(archive_path)

    # Optional sidecar bundle (env/TLS/xray) for disaster recovery — never
    # required for a normal restore of the DB file above.
    extras_needed = BACKUP_INCLUDE_ENV or (XRAY_JSON and os.path.isfile(XRAY_JSON))
    if extras_needed:
        tar_path = os.path.join(BACKUP_DIR, f"{ARCHIVE_PREFIX}{stamp}.tar.gz")
        with tempfile.TemporaryDirectory() as workdir:
            db_copy = os.path.join(workdir, os.path.basename(archive_path))
            shutil.copy2(archive_path, db_copy)
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
            with tarfile.open(tar_path, "w:gz") as tar:
                for entry in os.listdir(workdir):
                    tar.add(os.path.join(workdir, entry), arcname=entry)
            _chmod_owner_only(tar_path)

    logger.info("Backup created: %s", archive_path)
    prune_backups()
    return archive_path


def create_downloadable_backup() -> Tuple[str, str]:
    """Create a migration backup bundle and return ``(path, download_filename)``.

    Always packs DB + TLS + node control secrets into a ``.tar.gz`` so restoring
    onto a new server keeps existing node agents authenticated.
    """
    _ensure_dir()
    backend = _db_backend()
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    if backend == "sqlite":
        ext = "db"
    elif backend == "postgresql":
        ext = "dump"
    else:
        ext = "sql"
    bare_path = os.path.join(BACKUP_DIR, f"{ARCHIVE_PREFIX}{stamp}.{ext}")
    tar_path = os.path.join(BACKUP_DIR, f"{ARCHIVE_PREFIX}{stamp}.tar.gz")
    _dump_database_to(bare_path, backend)
    _chmod_owner_only(bare_path)
    with tempfile.TemporaryDirectory() as workdir:
        db_name = f"db.{ext}"
        shutil.copy2(bare_path, os.path.join(workdir, db_name))
        _dump_tls(workdir)
        _write_control_env_backup(workdir)
        if XRAY_JSON and os.path.isfile(XRAY_JSON):
            try:
                shutil.copy2(XRAY_JSON, os.path.join(workdir, "xray_config.json"))
            except OSError:
                logger.warning("Downloadable backup: could not copy xray_config.json", exc_info=True)
        with tarfile.open(tar_path, "w:gz") as tar:
            for entry in os.listdir(workdir):
                tar.add(os.path.join(workdir, entry), arcname=entry)
        _chmod_owner_only(tar_path)
    prune_backups()
    return tar_path, download_name(migration=True)


# ---------------------------------------------------------------------------
# List / prune / validate
# ---------------------------------------------------------------------------

_BACKUP_EXTS = (".dump", ".db", ".sql", ".tar.gz", ".tgz")


def _is_managed_backup_name(filename: str) -> bool:
    if not filename or filename.startswith("."):
        return False
    lower = filename.lower()
    if not any(lower.endswith(ext) for ext in _BACKUP_EXTS):
        return False
    return (
        filename.startswith(ARCHIVE_PREFIX)
        or bool(re.match(r"^[a-z0-9._-]+_\d{4}-\d{2}-\d{2}_\d{6}\.", lower))
    )


def detect_backup_kind(path: str) -> str:
    """Return ``pg_custom`` | ``sqlite`` | ``sql`` | ``tar`` | ``unknown``."""
    try:
        with open(path, "rb") as f:
            head = f.read(16)
    except OSError:
        return "unknown"
    if head.startswith(_PG_CUSTOM_MAGIC):
        return "pg_custom"
    if head.startswith(_SQLITE_MAGIC):
        return "sqlite"
    if head.startswith(_GZIP_MAGIC):
        return "tar"
    # Plain SQL text dumps (legacy NexusPanel / mysqldump).
    sample = head.lstrip()
    if sample.startswith((b"--", b"SET ", b"CREATE ", b"DROP ", b"BEGIN", b"PRAGMA")):
        return "sql"
    # UTF-8 BOM + SQL
    if head.startswith(b"\xef\xbb\xbf"):
        return "sql"
    return "unknown"


def _is_valid_backup_file(path: str) -> bool:
    kind = detect_backup_kind(path)
    if kind in ("pg_custom", "sqlite", "sql"):
        return True
    if kind == "tar":
        try:
            with tarfile.open(path, "r:gz") as tar:
                names = {os.path.basename(n) for n in tar.getnames()}
        except (tarfile.TarError, OSError, EOFError):
            return False
        known = {
            "db.sqlite3", "db.sql", "db.dump", "db.db",
            "xray_config.json",
        }
        # Also accept any member that itself looks like a DB dump.
        for n in names:
            if n.endswith((".dump", ".db", ".sql", ".sqlite3")):
                return True
        return bool(names & known)
    return False


# Back-compat alias used by older callers / tests.
def _is_valid_archive(path: str) -> bool:
    return _is_valid_backup_file(path)


def save_uploaded_backup(content: bytes, original_name: str = "") -> str:
    """Persist an uploaded backup into ``BACKUP_DIR``. Returns stored filename."""
    _ensure_dir()
    if not content:
        raise ValueError("Empty backup file")
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    raw_name = (original_name or "").strip()
    lower = raw_name.lower()
    if lower.endswith(".tar.gz") or lower.endswith(".tgz"):
        ext = ".tar.gz"
    elif lower.endswith(".dump"):
        ext = ".dump"
    elif lower.endswith(".db") or lower.endswith(".sqlite") or lower.endswith(".sqlite3"):
        ext = ".db"
    elif lower.endswith(".sql"):
        ext = ".sql"
    else:
        # Peek magic.
        if content.startswith(_PG_CUSTOM_MAGIC):
            ext = ".dump"
        elif content.startswith(_SQLITE_MAGIC):
            ext = ".db"
        elif content.startswith(_GZIP_MAGIC):
            ext = ".tar.gz"
        else:
            ext = ".dump"
    filename = f"{ARCHIVE_PREFIX}upload-{stamp}-{uuid4().hex[:8]}{ext}"
    dest = os.path.join(BACKUP_DIR, filename)
    with open(dest, "wb") as f:
        f.write(content)
    _chmod_owner_only(dest)
    if not _is_valid_backup_file(dest):
        try:
            os.remove(dest)
        except OSError:
            pass
        raise ValueError(
            "Uploaded file is not a valid NexusPanel backup "
            "(expected .dump / .db / .sql / .tar.gz)."
        )
    logger.info("Backup uploaded: %s", dest)
    prune_backups()
    return filename


def list_backups() -> List[str]:
    if not os.path.isdir(BACKUP_DIR):
        return []
    files = []
    for f in os.listdir(BACKUP_DIR):
        if not _is_managed_backup_name(f):
            continue
        path = os.path.join(BACKUP_DIR, f)
        if os.path.isfile(path):
            files.append(path)
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


def delete_backup(filename: str) -> None:
    match = next(
        (p for p in list_backups() if os.path.basename(p) == filename),
        None,
    )
    if match is None:
        raise FileNotFoundError(filename)
    os.remove(match)


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------

_PG_DUMP_SET_SKIP = (b"SET transaction_timeout",)


def _sanitize_pg_sql(path: str) -> None:
    tmp = path + ".sanitized"
    with open(path, "rb") as src, open(tmp, "wb") as out:
        for line in src:
            if line.startswith(_PG_DUMP_SET_SKIP):
                continue
            out.write(line)
    os.replace(tmp, path)


def _schedule_panel_restart() -> None:
    """Restart the panel so it reloads the restored DB (detached)."""
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


def _psql_admin(env: dict, appuser: str, *args: str, dbname: str = "postgres", **kwargs):
    """Run psql against a DB (prefer compose postgres service)."""
    compose_cmd = _compose_pg_cmd("psql")
    root = _compose_root()
    if compose_cmd:
        from app.db.base import engine
        # rebuild without the trailing tool args already in compose_cmd
        project = os.environ.get("COMPOSE_PROJECT_NAME", "nexuspanel").strip() or "nexuspanel"
        compose_file = _compose_file()
        cmd = [
            "docker", "compose", "-p", project, "-f", compose_file,
            "exec", "-T",
            "-e", "PGAPPNAME=nexuspanel-restore",
            "postgres",
            "psql", "-U", appuser, "-d", dbname, *args,
        ]
        return subprocess.run(cmd, cwd=root, env=env, **kwargs)
    from app.db.base import engine
    url = engine.url
    cmd = [
        "psql",
        "-h", str(url.host or "localhost"),
        "-p", str(url.port or 5432),
        "-U", appuser,
        "-d", dbname,
        *args,
    ]
    return subprocess.run(cmd, env=env, **kwargs)


def _pg_restore_failed(proc: subprocess.CompletedProcess) -> bool:
    """pg_restore exits 1 for some warnings; ignore known harmless ones."""
    if proc.returncode == 0:
        return False
    err = (proc.stderr or b"").decode(errors="replace")
    harmless = (
        "unrecognized configuration parameter \"transaction_timeout\"" in err
        and err.lower().count("error:") <= 1
    )
    if harmless and proc.returncode == 1:
        return False
    if proc.returncode > 1:
        return True
    return "ERROR" in err.upper()


def _verify_db_has_core_tables(env: dict, appuser: str, dbname: str) -> None:
    proc = _psql_admin(
        env, appuser,
        "-tA",
        "-c",
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name IN ('users','admins','alembic_version');",
        dbname=dbname,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    out = (proc.stdout or b"").decode().strip()
    try:
        n = int(out.splitlines()[-1] if out else "0")
    except ValueError:
        n = 0
    if n < 2:
        raise RuntimeError(
            f"Restored database '{dbname}' is missing core tables "
            f"(found {n}/3 of users/admins/alembic_version)."
        )
    # Also require at least the users relation to be queryable.
    proc2 = _psql_admin(
        env, appuser, "-tA", "-c", "SELECT count(*) FROM users;",
        dbname=dbname, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if proc2.returncode != 0:
        tail = (proc2.stderr or b"").decode(errors="replace")[-400:]
        raise RuntimeError(f"Restored database '{dbname}' users table unreadable: {tail.strip()}")


def _compose_pg_restore_into(dump_path: str, dbname: str, env: dict, appuser: str) -> None:
    """pg_restore dump into ``dbname`` via compose (file copy, not stdin)."""
    compose_file = _compose_file()
    if not compose_file or not shutil.which("docker"):
        raise RuntimeError("docker compose postgres service not available")
    project = os.environ.get("COMPOSE_PROJECT_NAME", "nexuspanel").strip() or "nexuspanel"
    root = _compose_root()
    remote = f"/tmp/nexuspanel-restore-{uuid4().hex[:10]}.dump"
    cp = subprocess.run(
        ["docker", "compose", "-p", project, "-f", compose_file, "cp", dump_path, f"postgres:{remote}"],
        cwd=root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    if cp.returncode != 0:
        # Fallback: host path readable by daemon — try absolute host path via
        # piping through `docker exec -i` only if cp failed (e.g. path mapping).
        tail = (cp.stderr or b"").decode(errors="replace")[-400:]
        raise RuntimeError(f"Cannot copy dump into postgres container: {tail.strip()}")
    try:
        cmd = [
            "docker", "compose", "-p", project, "-f", compose_file,
            "exec", "-T",
            "-e", "PGAPPNAME=nexuspanel-restore",
            "postgres",
            "pg_restore",
            "-U", appuser,
            "--no-owner", "--no-privileges",
            "--dbname", dbname,
            remote,
        ]
        proc = subprocess.run(
            cmd, cwd=root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        if _pg_restore_failed(proc):
            tail = (proc.stderr or b"").decode(errors="replace")[-800:]
            raise RuntimeError(f"pg_restore failed: {tail.strip()}")
    finally:
        subprocess.run(
            [
                "docker", "compose", "-p", project, "-f", compose_file,
                "exec", "-T", "postgres", "rm", "-f", remote,
            ],
            cwd=root, env=env, check=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )


def _local_pg_restore_into(dump_path: str, dbname: str, env: dict, appuser: str) -> None:
    from app.db.base import engine
    url = engine.url
    if not shutil.which("pg_restore"):
        raise RuntimeError("pg_restore not found")
    cmd = [
        "pg_restore",
        "-h", str(url.host or "localhost"),
        "-p", str(url.port or 5432),
        "-U", appuser,
        "--no-owner", "--no-privileges",
        "--dbname", dbname,
        dump_path,
    ]
    local_env = env.copy()
    local_env["PGAPPNAME"] = "nexuspanel-restore"
    proc = subprocess.run(cmd, env=local_env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if _pg_restore_failed(proc):
        tail = (proc.stderr or b"").decode(errors="replace")[-800:]
        raise RuntimeError(f"pg_restore failed: {tail.strip()}")


def _restore_postgres_custom(dump_path: str) -> None:
    """Atomically restore a custom-format dump without ever wiping the live DB.

    1. Create a temporary database
    2. pg_restore into the temp DB (live DB untouched)
    3. Verify core tables exist
    4. Rename live → old, temp → live
    5. Drop the old database

    If anything fails before the rename, the live database is unchanged.
    """
    from app.db.base import engine

    url = engine.url
    live = str(url.database)
    appuser = str(url.username or "postgres")
    env = _pg_env()
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    tmp_db = f"nexuspanel_restore_{stamp}"
    old_db = f"nexuspanel_old_{stamp}"

    engine.dispose()

    # --- 1) create empty temp DB -------------------------------------------------
    proc = _psql_admin(
        env, appuser,
        "-v", "ON_ERROR_STOP=1",
        "-c", f'DROP DATABASE IF EXISTS "{tmp_db}";',
        "-c", f'CREATE DATABASE "{tmp_db}" OWNER "{appuser}";',
        dbname="postgres",
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or b"").decode(errors="replace")[-600:]
        raise RuntimeError(f"Cannot create temporary restore database: {tail.strip()}")

    try:
        # --- 2) restore into temp (never touches live) ---------------------------
        try:
            _compose_pg_restore_into(dump_path, tmp_db, env, appuser)
        except RuntimeError as exc:
            logger.warning("Restore: compose path failed (%s); trying local pg_restore", exc)
            _local_pg_restore_into(dump_path, tmp_db, env, appuser)

        # --- 3) verify temp ------------------------------------------------------
        _verify_db_has_core_tables(env, appuser, tmp_db)

        # --- 4) swap names (only now is live affected) ---------------------------
        # Kick everyone off live so rename is allowed.
        kick = (
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname IN ('{live}', '{tmp_db}') AND pid <> pg_backend_pid();"
        )
        swap = (
            f'ALTER DATABASE "{live}" RENAME TO "{old_db}"; '
            f'ALTER DATABASE "{tmp_db}" RENAME TO "{live}";'
        )
        proc = _psql_admin(
            env, appuser,
            "-v", "ON_ERROR_STOP=1",
            "-c", kick,
            "-c", swap,
            dbname="postgres",
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        if proc.returncode != 0:
            tail = (proc.stderr or b"").decode(errors="replace")[-800:]
            raise RuntimeError(
                f"Restore imported OK into temporary DB but swap failed "
                f"(live database unchanged): {tail.strip()}"
            )

        # --- 5) drop previous live copy ------------------------------------------
        _psql_admin(
            env, appuser,
            "-c", kick.replace(f"'{tmp_db}'", f"'{old_db}'"),
            "-c", f'DROP DATABASE IF EXISTS "{old_db}";',
            dbname="postgres",
            check=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        logger.info("PostgreSQL custom dump restored atomically from %s", dump_path)
    except Exception:
        # Best-effort cleanup of temp DB; live is still intact if swap didn't run.
        _psql_admin(
            env, appuser,
            "-c", f'SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = \'{tmp_db}\' AND pid <> pg_backend_pid();',
            "-c", f'DROP DATABASE IF EXISTS "{tmp_db}";',
            dbname="postgres",
            check=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        raise
    finally:
        engine.dispose()


def _restore_postgres_sql(sql_src: str) -> None:
    """Plain SQL restore via the same atomic temp-DB swap as custom dumps."""
    _sanitize_pg_sql(sql_src)
    # Convert to a one-shot import into a temp DB using psql, then swap.
    from app.db.base import engine

    url = engine.url
    live = str(url.database)
    appuser = str(url.username or "postgres")
    env = _pg_env()
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    tmp_db = f"nexuspanel_restore_{stamp}"
    old_db = f"nexuspanel_old_{stamp}"

    engine.dispose()
    proc = _psql_admin(
        env, appuser,
        "-v", "ON_ERROR_STOP=1",
        "-c", f'DROP DATABASE IF EXISTS "{tmp_db}";',
        "-c", f'CREATE DATABASE "{tmp_db}" OWNER "{appuser}";',
        dbname="postgres",
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or b"").decode(errors="replace")[-600:]
        raise RuntimeError(f"Cannot create temporary restore database: {tail.strip()}")

    try:
        # Import SQL into temp.
        compose_file = _compose_file()
        if compose_file and shutil.which("docker"):
            project = os.environ.get("COMPOSE_PROJECT_NAME", "nexuspanel").strip() or "nexuspanel"
            root = _compose_root()
            remote = f"/tmp/nexuspanel-restore-{uuid4().hex[:10]}.sql"
            cp = subprocess.run(
                ["docker", "compose", "-p", project, "-f", compose_file, "cp", sql_src, f"postgres:{remote}"],
                cwd=root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )
            if cp.returncode != 0:
                raise RuntimeError("Cannot copy SQL dump into postgres container")
            try:
                proc = _psql_admin(
                    env, appuser,
                    "-v", "ON_ERROR_STOP=1",
                    "-f", remote,
                    dbname=tmp_db,
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                )
            finally:
                subprocess.run(
                    ["docker", "compose", "-p", project, "-f", compose_file,
                     "exec", "-T", "postgres", "rm", "-f", remote],
                    cwd=root, env=env, check=False,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
        else:
            proc = _psql_admin(
                env, appuser,
                "-v", "ON_ERROR_STOP=1",
                "-f", sql_src,
                dbname=tmp_db,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )
        if proc.returncode != 0:
            tail = (proc.stderr or b"").decode(errors="replace")[-800:]
            raise RuntimeError(f"PostgreSQL SQL restore failed: {tail.strip()}")

        _verify_db_has_core_tables(env, appuser, tmp_db)

        kick = (
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname IN ('{live}', '{tmp_db}') AND pid <> pg_backend_pid();"
        )
        swap = (
            f'ALTER DATABASE "{live}" RENAME TO "{old_db}"; '
            f'ALTER DATABASE "{tmp_db}" RENAME TO "{live}";'
        )
        proc = _psql_admin(
            env, appuser,
            "-v", "ON_ERROR_STOP=1",
            "-c", kick,
            "-c", swap,
            dbname="postgres",
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        if proc.returncode != 0:
            tail = (proc.stderr or b"").decode(errors="replace")[-800:]
            raise RuntimeError(
                f"SQL restore OK in temp DB but swap failed (live unchanged): {tail.strip()}"
            )
        _psql_admin(
            env, appuser,
            "-c", f'SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = \'{old_db}\' AND pid <> pg_backend_pid();',
            "-c", f'DROP DATABASE IF EXISTS "{old_db}";',
            dbname="postgres",
            check=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        logger.info("PostgreSQL SQL dump restored atomically from %s", sql_src)
    except Exception:
        _psql_admin(
            env, appuser,
            "-c", f'SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = \'{tmp_db}\' AND pid <> pg_backend_pid();',
            "-c", f'DROP DATABASE IF EXISTS "{tmp_db}";',
            dbname="postgres",
            check=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        raise
    finally:
        engine.dispose()


def _restore_sqlite_file(src: str) -> None:
    from app.db.base import engine

    if engine.dialect.name != "sqlite":
        raise RuntimeError("Cannot restore a SQLite .db onto a non-SQLite panel")
    dest = engine.url.database
    if not dest:
        raise RuntimeError("SQLite database path is not configured")
    engine.dispose()
    # Atomic replace: copy to temp next to the live DB, then os.replace.
    dest_dir = os.path.dirname(os.path.abspath(dest)) or "."
    fd, tmp = tempfile.mkstemp(prefix="restore-", suffix=".db", dir=dest_dir)
    os.close(fd)
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dest)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _restore_mysql_sql(sql_src: str) -> None:
    from app.db.base import engine

    if not shutil.which("mysql"):
        dest = os.path.join(BACKUP_DIR, "restore-db.sql")
        shutil.copy2(sql_src, dest)
        raise RuntimeError(
            f"Automatic MySQL restore requires the mysql CLI. "
            f"SQL dump extracted to {dest}."
        )
    url = engine.url
    cmd = [
        "mysql",
        "-h", url.host or "localhost",
        "-P", str(url.port or 3306),
        "-u", str(url.username or "root"),
        str(url.database),
    ]
    env = os.environ.copy()
    if url.password:
        env["MYSQL_PWD"] = str(url.password)
    engine.dispose()
    with open(sql_src, "rb") as sql_file:
        proc = subprocess.run(cmd, input=sql_file.read(), env=env, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        tail = (proc.stderr or b"").decode(errors="replace")[-800:]
        raise RuntimeError(f"MySQL restore failed: {tail.strip()}")


def _extract_safe(tar: tarfile.TarFile, workdir: str) -> None:
    for member in tar.getmembers():
        dest = os.path.normpath(os.path.join(workdir, member.name))
        abs_work = os.path.abspath(workdir)
        if not dest.startswith(abs_work + os.sep) and dest != abs_work:
            raise ValueError(f"Unsafe path in backup archive: {member.name}")
    tar.extractall(workdir, filter="data")


def _restore_path(path: str, restart_panel: bool = True, prepare: bool = True) -> None:
    from app.db.base import engine

    if not os.path.isfile(path):
        raise FileNotFoundError(path)

    kind = detect_backup_kind(path)
    backend = engine.dialect.name
    extras_workdir: Optional[str] = None
    tmp_ctx = None

    try:
        if kind == "pg_custom":
            if backend != "postgresql":
                raise RuntimeError("This backup is a PostgreSQL .dump but the panel is not on PostgreSQL")
            _restore_postgres_custom(path)
            logger.info("PostgreSQL custom dump restored from %s", path)
        elif kind == "sqlite":
            if backend != "sqlite":
                raise RuntimeError("This backup is a SQLite .db but the panel is not on SQLite")
            _restore_sqlite_file(path)
            logger.info("SQLite backup restored from %s", path)
        elif kind == "sql":
            if backend == "postgresql":
                _restore_postgres_sql(path)
                logger.info("PostgreSQL SQL dump restored from %s", path)
            elif backend == "mysql":
                _restore_mysql_sql(path)
                logger.info("MySQL dump restored from %s", path)
            elif backend == "sqlite":
                raise RuntimeError(
                    "Plain SQL dumps cannot be restored onto SQLite automatically; "
                    "use a .db backup from this panel."
                )
            else:
                raise RuntimeError(f"No SQL restore path for dialect {backend}")
        elif kind == "tar":
            tmp_ctx = tempfile.TemporaryDirectory()
            extras_workdir = tmp_ctx.name
            with tarfile.open(path, "r:gz") as tar:
                _extract_safe(tar, extras_workdir)
            candidates = []
            for name in os.listdir(extras_workdir):
                full = os.path.join(extras_workdir, name)
                if not os.path.isfile(full):
                    continue
                base = name.lower()
                if base in ("db.dump", "db.db", "db.sqlite3", "db.sql") or base.endswith(
                    (".dump", ".db", ".sqlite3", ".sql")
                ):
                    candidates.append(full)
            if not candidates:
                raise RuntimeError("Backup archive contains no database dump")

            def _rank(p: str) -> int:
                k = detect_backup_kind(p)
                return {"pg_custom": 0, "sqlite": 1, "sql": 2}.get(k, 9)

            candidates.sort(key=_rank)
            inner = candidates[0]
            _restore_path(inner, restart_panel=False, prepare=False)

            xray_src = os.path.join(extras_workdir, "xray_config.json")
            if os.path.isfile(xray_src) and XRAY_JSON:
                try:
                    shutil.copy2(xray_src, XRAY_JSON)
                except OSError:
                    logger.warning("Restore: could not write xray_config.json", exc_info=True)
        else:
            raise RuntimeError(
                "Unrecognized backup format. Upload a migration .tar.gz, "
                ".dump (PostgreSQL), or .db (SQLite)."
            )

        if prepare:
            _post_restore_prepare(workdir=extras_workdir)
    finally:
        if tmp_ctx is not None:
            tmp_ctx.cleanup()

    if restart_panel:
        _schedule_panel_restart()


def restore_backup(archive_path: str, restart_panel: bool = True) -> None:
    """Restore a backup file from disk. Destructive; restarts the panel."""
    _restore_path(archive_path, restart_panel=restart_panel)


def restore_from_bytes(content: bytes, original_name: str = "") -> str:
    """Validate, stage, and restore an uploaded backup. Returns stored filename."""
    stored = save_uploaded_backup(content, original_name)
    path = os.path.join(BACKUP_DIR, stored)
    try:
        restore_backup(path, restart_panel=True)
    except Exception:
        # Keep the uploaded file for retry; re-raise.
        raise
    return stored
