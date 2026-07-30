"""Runtime secrets live outside the git checkout (AUDIT_FINDINGS.md M16)."""
from __future__ import annotations

import os
from pathlib import Path

# Host path mounted at the same location inside the panel container.
RUNTIME_ENV_PATH = Path(
    os.environ.get("SHAHKAR_RUNTIME_ENV", "/var/lib/shahkar/.env")
)

# Keys that must never live in the repo-bound .env (under /code bind mount).
RUNTIME_SECRET_KEYS = frozenset(
    {
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "SQLALCHEMY_DATABASE_URL",
        "REDIS_PASSWORD",
        "REDIS_URL",
        "NODE_BOOTSTRAP_TOKEN",
        "NODE_CONTROL_SECRET",
        "METRICS_TOKEN",
        "SUDO_USERNAME",
        "SUDO_PASSWORD",
        "SUDO_PASSWORD_HASH",
    }
)

WEAK_POSTGRES_PASSWORDS = frozenset({"change-me", "changeme", "password", "postgres", ""})
