"""Test bootstrap.

Configures an isolated SQLite database and a stub ``xray`` binary *before* the
application package is imported (importing ``app`` instantiates the Xray core,
which shells out to the xray executable).
"""
import os
import pathlib
import tempfile

_tmp = pathlib.Path(tempfile.mkdtemp(prefix="nexuspanel-test-"))

# Stub xray so importing `app` doesn't require a real binary.
_xray = _tmp / "xray"
_xray.write_text(
    "#!/usr/bin/env bash\n"
    'case "$1" in\n'
    '  version) echo "Xray 1.8.4 (stub)";;\n'
    '  x25519) printf "Private key: k\\nPublic key: p\\n";;\n'
    "  *) echo stub;;\n"
    "esac\n"
)
_xray.chmod(0o755)
os.environ.setdefault("XRAY_EXECUTABLE_PATH", str(_xray))

os.environ["SQLALCHEMY_DATABASE_URL"] = f"sqlite:///{_tmp / 'test.db'}"
os.environ.setdefault("BACKUP_DIR", str(_tmp / "backups"))

import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _setup_database():
    import app.db.models  # noqa: F401  (register models on the metadata)
    from app.db.base import Base, engine

    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)
