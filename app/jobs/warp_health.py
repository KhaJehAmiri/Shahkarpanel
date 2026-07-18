"""Automatic Cloudflare WARP outbound health-check + self-heal.

The default WARP hostname (``engage.cloudflareclient.com``) almost always
resolves to the *same* Cloudflare anycast IP, so if that specific IP gets
blocked/dropped by a firewall/DPI somewhere along the path, a fresh DNS
lookup alone will not fix anything — the tunnel needs to move to a
*different* Cloudflare ingress IP:port. This job periodically confirms the
live WARP outbound(s) are actually passing real traffic and, once a given
outbound has been confirmed broken for several consecutive checks, scans a
list of known-good Cloudflare WARP IP:port candidates and switches to the
first one that works — automatically, without an admin having to notice and
manually re-save the config (see AUDIT_FINDINGS-style follow-up to
app/xray/warp_routing.py's endpoint pinning).

Applying the fix still means a brief (roughly 1-2s) restart of the whole
Xray core, since this panel's Xray API wrapper does not support hot-swapping
a single outbound without a restart (`xray_api/proxyman.py`'s
``add_outbound``/``remove_outbound`` are unimplemented). That is the same
trade-off `app.jobs.xray_core_health.core_health_check` already makes when
it detects the core itself is unhealthy, so this job follows the same
pattern rather than leaving WARP stuck broken indefinitely.
"""
from __future__ import annotations

import copy
import json
import time

from app import logger, scheduler, xray
from app.xray.warp_routing import apply_warp_endpoint, find_warp_outbounds, find_working_warp_endpoint
from config import (
    JOB_WARP_HEALTH_CHECK_ENABLED,
    JOB_WARP_HEALTH_CHECK_INTERVAL,
    WARP_HEALTH_FAILURE_THRESHOLD,
    WARP_HEALTH_REMEDIATION_COOLDOWN,
    XRAY_JSON,
)

_consecutive_failures: dict[str, int] = {}
_remediated_at: dict[str, float] = {}


def _probe(outbound: dict, all_outbounds: list[dict]) -> bool:
    """Real network probe: spins up a throwaway Xray process (doesn't touch
    the live core) and checks it can actually reach the internet through
    this exact outbound config. TCP-dial testing wouldn't work here — the
    WARP peer only speaks WireGuard/UDP — so this always forces the HTTP
    burstObservatory probe rather than the generic auto/tcp modes."""
    from app.utils.outbound_test import test_outbound

    try:
        result = test_outbound(outbound, all_outbounds, mode="http")
    except Exception:
        logger.exception("WARP health probe crashed for tag %s", outbound.get("tag"))
        return True  # a probe-side bug shouldn't trigger a false remediation
    return result.success


def _apply_and_restart(new_config: dict) -> bool:
    """Validate, snapshot, persist and restart the live core with
    ``new_config``. Mirrors the safety pipeline in
    ``app.routers.core.modify_core_config`` (test -> snapshot -> write ->
    restart -> rollback on failure), minus the parts that only make sense
    for an interactive admin request (permission deps, node/edge-nginx
    sync) — this job only ever touches the outbounds list.
    """
    import commentjson

    from app.routers.core import _xray_config_test_error
    from app.xray import XRayConfig
    from app.xray import config_history
    from app.xray.inbound_normalize import normalize_core_config_payload, runtime_core_config

    # Merge outbound fix into on-disk config so disabled inbounds are kept.
    try:
        with open(XRAY_JSON, "r", encoding="utf-8") as f:
            disk_payload = commentjson.loads(f.read())
    except OSError:
        disk_payload = copy.deepcopy(new_config)
    disk_payload = normalize_core_config_payload(disk_payload)
    disk_payload["outbounds"] = list(new_config.get("outbounds") or [])
    runtime_payload = runtime_core_config(disk_payload)

    test_err = _xray_config_test_error(dict(runtime_payload))
    if test_err:
        logger.error("WARP remediation produced an invalid config, aborting: %s", test_err)
        return False

    try:
        new_xray_config = XRayConfig(runtime_payload, api_port=xray.config.api_port)
    except ValueError:
        logger.exception("WARP remediation: failed to build XRayConfig")
        return False

    try:
        startup_config = new_xray_config.include_db_users()
    except Exception:
        logger.exception("WARP remediation: failed to merge DB users")
        return False

    previous_raw = None
    try:
        with open(XRAY_JSON, "r", encoding="utf-8") as f:
            previous_raw = f.read()
    except OSError:
        previous_raw = None
    if previous_raw:
        config_history.snapshot_config(previous_raw)

    prev_config = xray.config
    try:
        with open(XRAY_JSON, "w", encoding="utf-8") as f:
            f.write(json.dumps(disk_payload, indent=4))
    except OSError:
        logger.exception("WARP remediation: failed to write %s", XRAY_JSON)
        return False

    xray.config = new_xray_config
    try:
        # force=True: this job already gates restarts behind its own
        # failure-threshold + cooldown, so the generic health-restart
        # cooldown in xray.core.restart must not silently swallow it —
        # that would leave xray.config/disk pointing at the fix while the
        # live process keeps running the still-broken outbound.
        xray.core.restart(startup_config, force=True)
    except Exception:
        logger.exception("WARP remediation: core restart failed; rolling back")
        xray.config = prev_config
        if previous_raw:
            config_history.restore_config_file(previous_raw, XRAY_JSON)
            try:
                xray.core.restart(prev_config.include_db_users(), force=True)
            except Exception:
                logger.exception("WARP remediation rollback: restart with previous config failed")
        return False
    return True


def _remediate(tag: str) -> bool:
    config_dict = copy.deepcopy(dict(xray.config))
    outbounds = list(config_dict.get("outbounds") or [])
    target = next((o for o in outbounds if str(o.get("tag") or "") == tag), None)
    if target is None:
        return False

    found = find_working_warp_endpoint(target, lambda ob: _probe(ob, outbounds))
    if found is None:
        logger.error("WARP outbound '%s' is unreachable on every known candidate endpoint", tag)
        return False

    host, port = found
    if not apply_warp_endpoint(target, host, port):
        return False  # candidate is identical to what's already configured

    logger.warning("WARP outbound '%s' switching to %s:%s after health-check failures", tag, host, port)
    config_dict["outbounds"] = outbounds
    return _apply_and_restart(config_dict)


def warp_health_check() -> None:
    if not JOB_WARP_HEALTH_CHECK_ENABLED:
        return
    if xray.core.restarting:
        return

    try:
        from app.migration.state import migration_active
        if migration_active():
            return
    except ImportError:
        pass

    config_dict = dict(xray.config)
    outbounds = list(config_dict.get("outbounds") or [])
    warp_obs = find_warp_outbounds(outbounds)
    if not warp_obs:
        return

    now = time.time()
    for ob in warp_obs:
        tag = str(ob.get("tag") or "")
        if not tag:
            continue
        if now - _remediated_at.get(tag, 0) < WARP_HEALTH_REMEDIATION_COOLDOWN:
            continue

        if _probe(ob, outbounds):
            _consecutive_failures.pop(tag, None)
            continue

        failures = _consecutive_failures.get(tag, 0) + 1
        _consecutive_failures[tag] = failures
        logger.warning(
            "WARP outbound '%s' failed health probe (%s/%s)",
            tag, failures, WARP_HEALTH_FAILURE_THRESHOLD,
        )
        if failures >= WARP_HEALTH_FAILURE_THRESHOLD:
            _consecutive_failures[tag] = 0
            _remediated_at[tag] = now
            _remediate(tag)


from app.ha import run_if_leader  # noqa: E402

if JOB_WARP_HEALTH_CHECK_ENABLED:
    scheduler.add_job(
        run_if_leader(warp_health_check),
        'interval',
        seconds=JOB_WARP_HEALTH_CHECK_INTERVAL,
        coalesce=True,
        max_instances=1,
    )
