#!/usr/bin/env python3
"""Move production secrets out of the git-bound repo .env (AUDIT_FINDINGS.md M16).

Secrets are written to /var/lib/nexuspanel/.env (runtime) and stripped from the
repo .env under /opt/nexuspanel. Weak Postgres passwords are replaced and the
live database user is updated when reachable.

Usage:
  python3 scripts/migrate_runtime_secrets.py           # migrate if needed
  python3 scripts/migrate_runtime_secrets.py --dry-run
  python3 scripts/migrate_runtime_secrets.py --rotate-tokens
"""
from __future__ import annotations

import argparse
import os
import re
import secrets
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus, urlparse, urlunparse

ROOT = Path(__file__).resolve().parents[1]


def _load_runtime_env_constants():
    """Load app/runtime_env.py without importing the FastAPI ``app`` package.

    Host-side install/update runs this with system Python (no apscheduler /
    FastAPI). ``import app.runtime_env`` would execute ``app/__init__.py`` and
    fail with ModuleNotFoundError.
    """
    import importlib.util

    path = ROOT / "app" / "runtime_env.py"
    spec = importlib.util.spec_from_file_location("nexuspanel_runtime_env", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load runtime env constants from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.RUNTIME_ENV_PATH, mod.RUNTIME_SECRET_KEYS, mod.WEAK_POSTGRES_PASSWORDS


RUNTIME_ENV_PATH, RUNTIME_SECRET_KEYS, WEAK_POSTGRES_PASSWORDS = _load_runtime_env_constants()

_ENV_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)[ \t]*=[ \t]*(.*)$")


def _parse_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.is_file():
        return data
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = _ENV_LINE.match(line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if (val.startswith('"') and val.endswith('"')) or (
            val.startswith("'") and val.endswith("'")
        ):
            val = val[1:-1]
        data[key] = val
    return data


def _format_env(data: dict[str, str], header: str) -> str:
    lines = [header.rstrip(), ""]
    for key in sorted(data):
        val = data[key]
        if re.search(r"[\s#\"']", val) or val.startswith("$"):
            val = f'"{val}"'
        lines.append(f"{key}={val}")
    lines.append("")
    return "\n".join(lines)


def _rand(n: int = 32) -> str:
    return secrets.token_urlsafe(n)[: max(n, 16)]


def _postgres_url_with_password(url: str, password: str) -> str:
    parsed = urlparse(url)
    user = parsed.username or "nexuspanel"
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 5432
    db = (parsed.path or "/nexuspanel").lstrip("/") or "nexuspanel"
    netloc = f"{quote_plus(user)}:{quote_plus(password)}@{host}:{port}"
    return urlunparse(parsed._replace(netloc=netloc, path=f"/{db}"))


def _alter_postgres_password(
    *,
    user: str,
    old_password: str,
    new_password: str,
    host: str = "127.0.0.1",
    port: int = 5432,
    database: str = "nexuspanel",
) -> bool:
    env = os.environ.copy()
    env["PGPASSWORD"] = old_password
    sql = f"ALTER USER {user} WITH PASSWORD '{new_password.replace(chr(39), chr(39) + chr(39))}';"
    cmd = [
        "psql",
        "-h",
        host,
        "-p",
        str(port),
        "-U",
        user,
        "-d",
        database,
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        sql,
    ]
    try:
        subprocess.run(cmd, env=env, check=True, capture_output=True, text=True)
        return True
    except FileNotFoundError:
        pass
    except subprocess.CalledProcessError:
        pass

    compose = ROOT / "docker-compose.postgres.yml"
    if compose.is_file():
        project = os.environ.get("COMPOSE_PROJECT_NAME", "nexuspanel").strip() or "nexuspanel"
        docker_cmd = [
            "docker",
            "compose",
            "-p",
            project,
            "-f",
            str(compose),
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            user,
            "-d",
            database,
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            sql,
        ]
        try:
            subprocess.run(docker_cmd, check=True, capture_output=True, text=True)
            return True
        except subprocess.CalledProcessError:
            return False
    return False


def _needs_migration(repo: dict[str, str], runtime_env: Path) -> bool:
    if any(key in repo for key in RUNTIME_SECRET_KEYS):
        return True
    if "POSTGRES_PASSWORD" in repo and repo["POSTGRES_PASSWORD"] in WEAK_POSTGRES_PASSWORDS:
        return True
    if not runtime_env.is_file():
        return True
    return False


def migrate(
    *,
    repo_env: Path,
    runtime_env: Path,
    dry_run: bool = False,
    rotate_tokens: bool = False,
    if_needed: bool = False,
) -> int:
    repo = _parse_env(repo_env)
    runtime = _parse_env(runtime_env)

    if if_needed and not _needs_migration(repo, runtime_env):
        print("Runtime secrets already isolated; nothing to do.")
        return 0

    moved: dict[str, str] = {}
    for key in RUNTIME_SECRET_KEYS:
        if key in repo and key not in runtime:
            moved[key] = repo[key]
        elif key in repo:
            moved[key] = runtime.get(key, repo[key])
        elif key in runtime:
            moved[key] = runtime[key]

    pg_pass = moved.get("POSTGRES_PASSWORD", runtime.get("POSTGRES_PASSWORD", ""))
    if pg_pass in WEAK_POSTGRES_PASSWORDS or not pg_pass:
        old_pg = pg_pass or "change-me"
        pg_pass = _rand(40)
        moved["POSTGRES_PASSWORD"] = pg_pass
        user = moved.get("POSTGRES_USER") or repo.get("POSTGRES_USER") or "nexuspanel"
        db = moved.get("POSTGRES_DB") or repo.get("POSTGRES_DB") or "nexuspanel"
        moved["POSTGRES_USER"] = user
        moved["POSTGRES_DB"] = db
        url = moved.get("SQLALCHEMY_DATABASE_URL") or repo.get("SQLALCHEMY_DATABASE_URL", "")
        if url.startswith("postgresql"):
            moved["SQLALCHEMY_DATABASE_URL"] = _postgres_url_with_password(url, pg_pass)
        else:
            moved["SQLALCHEMY_DATABASE_URL"] = (
                f"postgresql://{quote_plus(user)}:{quote_plus(pg_pass)}@127.0.0.1:5432/{db}"
            )
        if not dry_run and old_pg:
            ok = _alter_postgres_password(user=user, old_password=old_pg, new_password=pg_pass)
            if ok:
                print("Postgres password updated via ALTER USER.")
            else:
                print(
                    "WARNING: could not ALTER USER in Postgres — update the DB password manually.",
                    file=sys.stderr,
                )
    elif "SQLALCHEMY_DATABASE_URL" not in moved and repo.get("SQLALCHEMY_DATABASE_URL"):
        moved["SQLALCHEMY_DATABASE_URL"] = repo["SQLALCHEMY_DATABASE_URL"]

    redis_pw = moved.get("REDIS_PASSWORD") or repo.get("REDIS_PASSWORD", "")
    if redis_pw and "REDIS_URL" not in moved:
        moved["REDIS_URL"] = f"redis://:{quote_plus(redis_pw)}@127.0.0.1:6379/0"
    elif repo.get("REDIS_URL"):
        moved.setdefault("REDIS_URL", repo["REDIS_URL"])

    if rotate_tokens:
        moved["NODE_BOOTSTRAP_TOKEN"] = _rand(40)
        moved["METRICS_TOKEN"] = _rand(40)
        print("Rotated NODE_BOOTSTRAP_TOKEN and METRICS_TOKEN.")
        print(
            "NODE_CONTROL_SECRET was kept (rotate manually and update every node agent).",
        )

    runtime_header = (
        f"# Runtime secrets — outside git checkout ({runtime_env})\n"
        f"# Migrated on {datetime.now(timezone.utc).isoformat()}\n"
        "# Do not commit this file."
    )
    runtime_body = _format_env({k: moved[k] for k in sorted(moved)}, runtime_header)

    repo_clean = {k: v for k, v in repo.items() if k not in RUNTIME_SECRET_KEYS}
    repo_header = (
        f"# Repo configuration (no secrets — see {runtime_env})\n"
        f"# Secrets migrated on {datetime.now(timezone.utc).isoformat()}"
    )
    repo_body = _format_env(repo_clean, repo_header)

    if dry_run:
        print(f"Would write runtime secrets to {runtime_env} ({len(moved)} keys)")
        print(f"Would strip secrets from {repo_env} ({len(repo) - len(repo_clean)} keys removed)")
        return 0

    runtime_env.parent.mkdir(parents=True, exist_ok=True)
    if runtime_env.is_file():
        backup = runtime_env.with_suffix(f".bak.{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}")
        shutil.copy2(runtime_env, backup)
    runtime_env.write_text(runtime_body, encoding="utf-8")
    os.chmod(runtime_env, 0o600)
    try:
        import pwd

        uid = pwd.getpwnam("nexuspanel").pw_uid
        gid = pwd.getpwnam("nexuspanel").pw_gid
        os.chown(runtime_env, uid, gid)
    except (ImportError, KeyError, OSError):
        pass

    if repo_env.is_file():
        backup = repo_env.with_suffix(f".bak.{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}")
        shutil.copy2(repo_env, backup)
        print(f"Repo .env backed up to {backup}")

    repo_env.write_text(repo_body, encoding="utf-8")
    os.chmod(repo_env, 0o600)

    print(f"Runtime secrets written to {runtime_env}")
    print(f"Secrets removed from {repo_env}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-env",
        type=Path,
        default=ROOT / ".env",
        help="Repo-bound .env path (default: %(default)s)",
    )
    parser.add_argument(
        "--runtime-env",
        type=Path,
        default=RUNTIME_ENV_PATH,
        help="Runtime secrets path (default: %(default)s)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--rotate-tokens",
        action="store_true",
        help="Rotate NODE_BOOTSTRAP_TOKEN and METRICS_TOKEN (not NODE_CONTROL_SECRET)",
    )
    parser.add_argument(
        "--if-needed",
        action="store_true",
        help="Exit 0 without changes when secrets are already isolated",
    )
    args = parser.parse_args()
    return migrate(
        repo_env=args.repo_env,
        runtime_env=args.runtime_env,
        dry_run=args.dry_run,
        rotate_tokens=args.rotate_tokens,
        if_needed=args.if_needed,
    )


if __name__ == "__main__":
    raise SystemExit(main())
