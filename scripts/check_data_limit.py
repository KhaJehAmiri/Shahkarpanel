#!/usr/bin/env python3
"""End-to-end data-limit verification (WireGuard + central quota).

Runs the full limit cycle: transfer over quota → strict cap → peer pause → recharge.

Environment variables (same as wg_smoke_test / wg_limit_test):
  WG_NODE_SSH_PASSWORD   — SSH to WG node (required for external iperf test)
  WG_SMOKE_PANEL         — Panel base URL (default http://127.0.0.1:8000)
  WG_LIMIT_USERNAME      — Test username (default wg_smoke_test)
  WG_SMOKE_NODE_ID       — WireGuard node id (default 1)

Examples:
  cd /opt/nexuspanel
  WG_NODE_SSH_PASSWORD='…' python3 scripts/check_data_limit.py

  # Quota unit tests only (no live nodes):
  python3 scripts/check_data_limit.py --unit-only
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify central data-limit enforcement")
    parser.add_argument(
        "--unit-only",
        action="store_true",
        help="Run pytest quota/accounting tests only (no live WG transfer)",
    )
    args = parser.parse_args()

    unit = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_quota.py", "tests/test_subscription_guards.py", "-q"],
        cwd=ROOT,
    )
    if unit.returncode != 0:
        return unit.returncode

    if args.unit_only:
        print("Unit tests passed.")
        return 0

    limit = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "wg_limit_test.py"), *sys.argv[1:]],
        cwd=ROOT,
    )
    return limit.returncode


if __name__ == "__main__":
    raise SystemExit(main())
