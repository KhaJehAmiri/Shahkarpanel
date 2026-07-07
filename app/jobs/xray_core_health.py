"""Stable import path for ``0_xray_core.py`` (filename starts with a digit)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_IMPL = Path(__file__).resolve().parent / "0_xray_core.py"
_spec = importlib.util.spec_from_file_location("nexuspanel.jobs._xray_core_impl", _IMPL)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Cannot load xray core health job from {_IMPL}")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

core_health_check = _mod.core_health_check
