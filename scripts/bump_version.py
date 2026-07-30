#!/usr/bin/env python3
"""Bump Shahkar semver in VERSION, app/__init__.py, and dashboard package.json."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"
INIT_FILE = ROOT / "app" / "__init__.py"
PKG_FILE = ROOT / "app" / "dashboard-next" / "package.json"


def read_version() -> str:
    if VERSION_FILE.is_file():
        return VERSION_FILE.read_text().strip()
    text = INIT_FILE.read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
    if not m:
        raise SystemExit("Could not find __version__")
    return m.group(1)


def parse_semver(v: str) -> tuple[int, int, int]:
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)$", v.strip())
    if not m:
        raise SystemExit(f"Invalid semver: {v}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def bump(current: str, part: str) -> str:
    major, minor, patch = parse_semver(current)
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def write_version(version: str) -> None:
    VERSION_FILE.write_text(version + "\n", encoding="utf-8")
    init = INIT_FILE.read_text(encoding="utf-8")
    if "_read_version()" not in init:
        init_new, n = re.subn(
            r'(__version__\s*=\s*["\'])[^"\']+(["\'])',
            rf"\g<1>{version}\g<2>",
            init,
            count=1,
        )
        if n != 1:
            raise SystemExit("Failed to update app/__init__.py")
        INIT_FILE.write_text(init_new, encoding="utf-8")

    if PKG_FILE.is_file():
        pkg = PKG_FILE.read_text(encoding="utf-8")
        pkg_new, n2 = re.subn(
            r'("version"\s*:\s*")[^"]+(")',
            rf"\g<1>{version}\g<2>",
            pkg,
            count=1,
        )
        if n2 == 1:
            PKG_FILE.write_text(pkg_new, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bump Shahkar version")
    parser.add_argument("target", nargs="?", help="Explicit version (e.g. 0.9.0) or patch|minor|major")
    args = parser.parse_args()
    current = read_version()
    if not args.target:
        new = bump(current, "patch")
    elif args.target in ("patch", "minor", "major"):
        new = bump(current, args.target)
    else:
        new = args.target.strip()
        parse_semver(new)
    write_version(new)
    print(new)


if __name__ == "__main__":
    main()
