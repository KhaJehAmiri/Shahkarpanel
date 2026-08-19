"""Importable boot hook for the worker (``0_xray_core`` filename starts with a digit)."""


def start_core():
    from app.jobs.xray_core_health import start_core as _start_core

    return _start_core()
