"""Detect leftover Alembic revision copies before ScriptDirectory loads them.

A file like ``b-gg77bb88cc99_branding_admin_scope.py`` (editor/scp backup)
keeps the same ``revision = "gg77bb88cc99"`` as the real migration. Alembic
then raises ``DuplicateRevisionError`` and the panel container exits 255 in a
restart loop.

Backup-looking extras are quarantined (renamed ``*.py.disabled``). Real
duplicate revisions still fail, but with a readable file list.
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

REVISION_RE = re.compile(r"^revision\s*=\s*['\"]([^'\"]+)['\"]", re.M)
BACKUP_NAME_RE = re.compile(
    r"^(b-|copy-|Copy of |Copy of)",
    re.I,
)


def _versions_dir(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    return Path(__file__).resolve().parent / "versions"


def _read_revision(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = REVISION_RE.search(text)
    return match.group(1) if match else None


def _is_backup_name(name: str) -> bool:
    if name.endswith(".disabled") or name.endswith(".bak") or name.endswith("~"):
        return True
    return bool(BACKUP_NAME_RE.match(name))


def scan_revision_files(versions_dir: Path) -> Dict[str, List[Path]]:
    by_rev: Dict[str, List[Path]] = defaultdict(list)
    if not versions_dir.is_dir():
        return by_rev
    for path in versions_dir.iterdir():
        if not path.is_file() or path.suffix != ".py":
            continue
        if path.name.endswith(".py.disabled"):
            continue
        rev = _read_revision(path)
        if rev:
            by_rev[rev].append(path)
    return by_rev


def quarantine_duplicate_revisions(versions_dir: Path | None = None) -> List[str]:
    """Move backup-looking duplicate revision files aside.

    Returns log lines describing what happened. Raises ``SystemExit`` if a
    non-backup duplicate remains (panel must not start with a broken graph).
    """
    directory = _versions_dir(versions_dir)
    by_rev = scan_revision_files(directory)
    notes: List[str] = []
    fatal: List[Tuple[str, List[Path]]] = []

    for rev, paths in sorted(by_rev.items()):
        if len(paths) < 2:
            continue
        backups = [p for p in paths if _is_backup_name(p.name)]
        keepers = [p for p in paths if p not in backups]
        if not keepers:
            # Every copy looks like a backup — keep the shortest name.
            keepers = [min(paths, key=lambda p: (len(p.name), p.name))]
            backups = [p for p in paths if p not in keepers]
        for path in backups:
            dest = path.with_name(path.name + ".disabled")
            try:
                if dest.exists():
                    dest = path.with_name(f"{path.name}.{path.stat().st_mtime_ns}.disabled")
                path.rename(dest)
                notes.append(f"quarantined duplicate alembic file {path.name} -> {dest.name}")
            except OSError as exc:
                fatal.append((rev, paths))
                notes.append(f"could not quarantine {path.name}: {exc}")
        leftover = [p for p in keepers]
        # Re-scan this revision after moves.
        still = [p for p in leftover if p.exists()]
        if len(still) > 1:
            fatal.append((rev, still))

    if fatal:
        bits = []
        for rev, paths in fatal:
            names = ", ".join(p.name for p in paths)
            bits.append(f"{rev}: {names}")
        raise SystemExit(
            "alembic: duplicate revision id(s) — remove extras and retry: "
            + "; ".join(bits)
        )
    return notes


def main(argv: List[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    directory = Path(args[0]) if args else None
    try:
        notes = quarantine_duplicate_revisions(directory)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 2
    for line in notes:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
