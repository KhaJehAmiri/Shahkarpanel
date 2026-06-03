import os
import tarfile

from app import backup


def test_backup_creates_archive_with_database():
    path = backup.create_backup()
    assert os.path.isfile(path)
    with tarfile.open(path) as tar:
        names = tar.getnames()
    assert "db.sqlite3" in names


def test_backup_is_listed():
    path = backup.create_backup()
    listed = backup.list_backups()
    assert path in listed


def test_sqlite_restore_roundtrip():
    path = backup.create_backup()
    # Should not raise for SQLite.
    backup.restore_backup(path)
