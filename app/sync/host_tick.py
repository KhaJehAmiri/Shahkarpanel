"""Isolated host CPU/RAM publisher.

The worker GIL is often held for ~2s by fleet QueryStats / census SQL, which
made Overview gauges freeze. This loop runs in a child process with its own
GIL and only reads ``/proc`` + Redis.
"""
from __future__ import annotations

import json
import os
import time
from multiprocessing import get_context
from typing import Optional

HOST_KEY = "shahkar:live:host"
SNAPSHOT_KEY = "shahkar:live:snapshot"
LIVE_CHANNEL = "shahkar:live"
HOST_TTL = 15
TICK_SEC = 0.25
CPU_WINDOW_SEC = 1.0
HOST_FIELDS = ("cpu_usage", "cpu_cores", "mem_used", "mem_total")

_proc: Optional[Process] = None


def read_meminfo() -> tuple[int, int] | None:
    """Return (MemTotal, MemAvailable) bytes — same as ``free`` / htop."""
    total = avail = None
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1]) * 1024
                elif line.startswith("MemAvailable:"):
                    avail = int(line.split()[1]) * 1024
                if total is not None and avail is not None:
                    return total, avail
    except (OSError, ValueError, IndexError):
        return None
    return None


def read_cpu_times() -> tuple[int, int] | None:
    """Return (busy, total) jiffies from ``/proc/stat``."""
    try:
        with open("/proc/stat", encoding="utf-8") as fh:
            parts = fh.readline().split()
        nums = [int(x) for x in parts[1:8]]
        idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
        total = sum(nums)
        return total - idle, total
    except (OSError, ValueError, IndexError):
        return None


def read_cpu_cores() -> int:
    n = 0
    try:
        with open("/proc/stat", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("cpu") and len(line) > 3 and line[3].isdigit():
                    n += 1
                elif n and not line.startswith("cpu"):
                    break
    except OSError:
        n = 0
    return n or int(os.cpu_count() or 1)


def cpu_percent_from_hist(
    hist: list[tuple[float, int, int]], busy: int, total: int, now: float
) -> tuple[list[tuple[float, int, int]], Optional[float]]:
    """Sliding ~1s window. Returns (hist, percent or None on first sample)."""
    hist.append((now, busy, total))
    cutoff = now - CPU_WINDOW_SEC
    drop_to = 0
    for i, (ts, _b, _t) in enumerate(hist):
        if ts >= cutoff:
            drop_to = max(0, i - 1)
            break
    if drop_to:
        del hist[:drop_to]
    if len(hist) > 16:
        del hist[:-16]
    prev = hist[0]
    if len(hist) < 2 or total <= prev[2]:
        return hist, None
    d_total = total - prev[2]
    d_busy = busy - prev[1]
    pct = round(max(0.0, min(100.0, 100.0 * d_busy / d_total)), 1)
    return hist, pct


def _redis():
    url = os.environ.get("REDIS_URL") or ""
    if not url:
        return None
    import redis

    return redis.Redis.from_url(
        url,
        decode_responses=True,
        socket_connect_timeout=0.4,
        socket_timeout=0.4,
    )


def publish_host_sample(client, host: dict) -> None:
    raw_host = json.dumps(host, separators=(",", ":"))
    pipe = client.pipeline()
    pipe.set(HOST_KEY, raw_host, ex=HOST_TTL)
    pipe.get(SNAPSHOT_KEY)
    got = pipe.execute()
    snap_raw = got[1] if len(got) > 1 else None
    try:
        snap = json.loads(snap_raw) if snap_raw else {}
        if not isinstance(snap, dict):
            snap = {}
    except (TypeError, ValueError, json.JSONDecodeError):
        snap = {}
    snap.update(host)
    snap["kind"] = "tick"
    payload = json.dumps(snap, default=str, separators=(",", ":"))
    client.publish(LIVE_CHANNEL, payload)


def run_loop() -> None:
    client = None
    hist: list[tuple[float, int, int]] = []
    last_pct = 0.0
    have_pct = False
    cores = read_cpu_cores()
    while True:
        t0 = time.monotonic()
        try:
            if client is None:
                client = _redis()
            times = read_cpu_times()
            mem = read_meminfo()
            if times is not None:
                hist, pct = cpu_percent_from_hist(hist, times[0], times[1], t0)
                if pct is not None:
                    last_pct = pct
                    have_pct = True
            host = {
                "cpu_cores": int(cores),
                "t": time.time(),
            }
            if have_pct:
                host["cpu_usage"] = float(last_pct)
            if mem is not None:
                total, avail = mem
                host["mem_total"] = int(total)
                host["mem_used"] = max(0, int(total) - int(avail))
            if client is not None:
                try:
                    publish_host_sample(client, host)
                except Exception:
                    try:
                        client.close()
                    except Exception:
                        pass
                    client = None
        except Exception:
            client = None
        leftover = TICK_SEC - (time.monotonic() - t0)
        time.sleep(leftover if leftover > 0.02 else 0.02)


def start_host_tick_process() -> None:
    """Daemon child: 250ms CPU/RAM WebSocket ticks, independent of the worker GIL."""
    global _proc
    if _proc is not None and _proc.is_alive():
        return
    # spawn: never fork the worker after other threads exist (deadlock risk).
    ctx = get_context("spawn")
    _proc = ctx.Process(target=run_loop, name="overview-host-tick", daemon=True)
    _proc.start()
