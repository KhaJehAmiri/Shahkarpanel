"""Outbound connectivity tests — 3x-ui parity (TCP dial + HTTP burstObservatory probe)."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

import requests

from config import XRAY_ASSETS_PATH, XRAY_EXECUTABLE_PATH

DEFAULT_TEST_URL = "https://cp.cloudflare.com/"
PROBE_URLS = (
    "https://cp.cloudflare.com/",
    "https://www.google.com/generate_204",
    "http://1.1.1.1/",
)
HTTP_TEST_LOCK = threading.Lock()


@dataclass
class EndpointResult:
    address: str
    success: bool
    delay: int = 0
    error: str = ""


@dataclass
class OutboundTestResult:
    success: bool
    delay: int = 0
    error: str = ""
    mode: str = ""
    endpoints: list[EndpointResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "success": self.success,
            "delay": self.delay,
            "mode": self.mode,
        }
        if self.error:
            out["error"] = self.error
        if self.endpoints:
            out["endpoints"] = [
                {
                    "address": e.address,
                    "success": e.success,
                    "delay": e.delay,
                    **({"error": e.error} if e.error else {}),
                }
                for e in self.endpoints
            ]
        return out


def test_outbound(
    outbound: dict[str, Any],
    all_outbounds: list[dict[str, Any]] | None = None,
    test_url: str = "",
    mode: str = "",
) -> OutboundTestResult:
    """Test an outbound. mode: auto (default), http, or tcp."""
    all_out = all_outbounds or []
    m = (mode or "auto").lower()
    protocol = str(outbound.get("protocol") or "")
    tag = str(outbound.get("tag") or "")

    if protocol == "blackhole" or tag == "BLOCK":
        return OutboundTestResult(success=False, mode=m or "auto", error="Blocked/blackhole outbound cannot be tested")

    if m == "tcp":
        return _test_outbound_tcp(outbound)

    if m == "http":
        return _test_outbound_http(outbound, all_out, test_url)

    # auto — full HTTP probe first, then TCP reachability fallback
    http = _test_outbound_http(outbound, all_out, test_url)
    if http.success:
        return http

    tcp = _test_outbound_tcp(outbound)
    if tcp.success:
        tcp.mode = "tcp"
        return tcp

    return http


def _num_as_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _add_server(out: list[str], addr: Any, port: Any) -> None:
    host = str(addr or "").strip()
    p = _num_as_int(port)
    if host and p > 0:
        out.append(f"{host}:{p}")


def extract_outbound_endpoints(outbound: dict[str, Any]) -> list[str]:
    protocol = str(outbound.get("protocol") or "")
    settings = outbound.get("settings") or {}
    if not isinstance(settings, dict):
        return []

    out: list[str] = []
    if protocol in ("vmess",):
        for item in settings.get("vnext") or []:
            if isinstance(item, dict):
                _add_server(out, item.get("address"), item.get("port"))
    elif protocol == "vless":
        if settings.get("address"):
            _add_server(out, settings.get("address"), settings.get("port"))
        for item in settings.get("vnext") or []:
            if isinstance(item, dict):
                _add_server(out, item.get("address"), item.get("port"))
    elif protocol in ("trojan", "shadowsocks", "http", "socks"):
        for item in settings.get("servers") or []:
            if isinstance(item, dict):
                _add_server(out, item.get("address"), item.get("port"))
    elif protocol == "wireguard":
        for peer in settings.get("peers") or []:
            if isinstance(peer, dict):
                ep = str(peer.get("endpoint") or "").strip()
                if ep:
                    out.append(ep)
    return out


def _probe_tcp_endpoint(endpoint: str, timeout: float = 5.0) -> EndpointResult:
    result = EndpointResult(address=endpoint, success=False)
    host, _, port_str = endpoint.rpartition(":")
    start = time.time()
    try:
        with socket.create_connection((host, int(port_str)), timeout=timeout):
            result.success = True
            result.delay = max(1, int((time.time() - start) * 1000))
    except Exception as err:
        result.error = str(err)
        result.delay = max(1, int((time.time() - start) * 1000))
    return result


def _test_outbound_tcp(outbound: dict[str, Any]) -> OutboundTestResult:
    protocol = str(outbound.get("protocol") or "")
    endpoints = extract_outbound_endpoints(outbound)
    if protocol == "freedom" and not endpoints:
        endpoints = ["1.1.1.1:443"]
    if protocol == "dns" and not endpoints:
        endpoints = ["1.1.1.1:53"]
    if not endpoints:
        return OutboundTestResult(success=False, mode="tcp", error="No testable endpoint")

    results: list[EndpointResult] = []
    with ThreadPoolExecutor(max_workers=min(4, len(endpoints))) as pool:
        futures = {pool.submit(_probe_tcp_endpoint, ep): ep for ep in endpoints}
        for fut in as_completed(futures):
            results.append(fut.result())

    best = min((r.delay for r in results if r.success), default=-1)
    first_err = next((r.error for r in results if not r.success and r.error), "")
    out = OutboundTestResult(success=best >= 0, mode="tcp", endpoints=results)
    if best >= 0:
        out.delay = best
    else:
        out.error = first_err or "All endpoints unreachable"
    return out


def _outbounds_contain_tag(outbounds: list[dict[str, Any]], tag: str) -> bool:
    return any(str(o.get("tag") or "") == tag for o in outbounds)


def _find_available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_port(port: int, timeout: float = 8.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.15):
                return
        except OSError:
            time.sleep(0.08)
    raise TimeoutError(f"port {port} not ready after {timeout}s")


def _prepare_outbounds(outbounds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for ob in outbounds:
        item = json.loads(json.dumps(ob))
        if str(item.get("protocol") or "") == "wireguard":
            settings = item.setdefault("settings", {})
            if isinstance(settings, dict):
                settings["noKernelTun"] = True
        prepared.append(item)
    return prepared


def _create_test_config(
    outbound_tag: str,
    all_outbounds: list[dict[str, Any]],
    metrics_port: int,
    probe_url: str,
) -> dict[str, Any]:
    return {
        "log": {"loglevel": "warning", "access": "none", "error": "none", "dnsLog": False},
        "dns": {
            "servers": ["https://1.1.1.1/dns-query", "1.1.1.1", "8.8.8.8"],
            "queryStrategy": "UseIPv4",
        },
        "inbounds": [],
        "outbounds": _prepare_outbounds(all_outbounds),
        "routing": {"domainStrategy": "AsIs", "rules": []},
        "policy": {},
        "stats": {},
        "burstObservatory": {
            "subjectSelector": [outbound_tag],
            "pingConfig": {
                "destination": probe_url,
                "interval": "1s",
                "connectivity": "",
                "timeout": "5s",
                "samplingCount": 1,
            },
        },
        "metrics": {"tag": "test-metrics", "listen": f"127.0.0.1:{metrics_port}"},
    }


def _fetch_observatory_entry(metrics_port: int, tag: str) -> tuple[dict[str, Any], bool]:
    try:
        resp = requests.get(f"http://127.0.0.1:{metrics_port}/debug/vars", timeout=2)
        if resp.status_code != 200:
            return {}, False
        payload = resp.json()
        observatory = payload.get("observatory") or {}
        if not isinstance(observatory, dict):
            return {}, False
        if tag in observatory and isinstance(observatory[tag], dict):
            return observatory[tag], True
        for entry in observatory.values():
            if isinstance(entry, dict) and entry.get("outbound_tag") == tag:
                return entry, True
    except Exception:
        pass
    return {}, False


def _observatory_failed(entry: dict[str, Any]) -> bool:
    if entry.get("alive"):
        return False
    hp = entry.get("health_ping") or {}
    if not isinstance(hp, dict):
        return False
    total = _num_as_int(hp.get("all"))
    failed = _num_as_int(hp.get("fail"))
    return total >= 2 and failed >= total


def _poll_observatory_result(proc: subprocess.Popen[Any], metrics_port: int, tag: str, timeout: float = 10.0) -> OutboundTestResult:
    deadline = time.time() + timeout
    last_entry: dict[str, Any] = {}
    saw_entry = False
    while time.time() < deadline:
        if proc.poll() is not None:
            tail = (proc.stdout.read() if proc.stdout else b"").decode("utf-8", errors="replace")[-500:]
            return OutboundTestResult(
                success=False,
                mode="http",
                error=f"Xray process exited: {tail or proc.returncode}",
            )
        entry, ok = _fetch_observatory_entry(metrics_port, tag)
        if ok:
            if entry.get("alive"):
                delay = int(entry.get("delay") or 1)
                return OutboundTestResult(success=True, mode="http", delay=max(delay, 1))
            last_entry = entry
            saw_entry = True
            if _observatory_failed(entry):
                reason = str(entry.get("last_error_reason") or "").strip()
                err = reason or "HTTP probe failed through outbound"
                return OutboundTestResult(success=False, mode="http", error=err)
        time.sleep(0.35)

    msg = "HTTP probe timed out"
    if saw_entry:
        reason = str(last_entry.get("last_error_reason") or "").strip()
        if reason:
            msg = reason
        elif _observatory_failed(last_entry):
            msg = "HTTP probe failed through outbound"
    return OutboundTestResult(success=False, mode="http", error=msg)


def _probe_urls(test_url: str) -> tuple[str, ...]:
    if test_url.strip():
        return (test_url.strip(),)
    return PROBE_URLS


def _test_outbound_http_once(
    outbound: dict[str, Any],
    all_outbounds: list[dict[str, Any]],
    probe_url: str,
) -> OutboundTestResult:
    tag = str(outbound.get("tag") or "")
    if not tag:
        return OutboundTestResult(success=False, mode="http", error="Outbound has no tag")

    if not _outbounds_contain_tag(all_outbounds, tag):
        all_outbounds = [*all_outbounds, outbound]

    if not HTTP_TEST_LOCK.acquire(blocking=False):
        return OutboundTestResult(
            success=False,
            mode="http",
            error="Another outbound test is already running, please wait",
        )

    proc: subprocess.Popen[Any] | None = None
    config_path = ""
    try:
        metrics_port = _find_available_port()
        config = _create_test_config(tag, all_outbounds, metrics_port, probe_url)
        fd, config_path = tempfile.mkstemp(prefix="xray_outbound_test_", suffix=".json")
        with os.fdopen(fd, "w") as fh:
            json.dump(config, fh)

        env = os.environ.copy()
        env["XRAY_LOCATION_ASSET"] = XRAY_ASSETS_PATH
        proc = subprocess.Popen(
            [XRAY_EXECUTABLE_PATH, "run", "-config", config_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            text=False,
        )
        _wait_for_port(metrics_port, timeout=8)
        if proc.poll() is not None:
            tail = (proc.stdout.read() if proc.stdout else b"").decode("utf-8", errors="replace")[-500:]
            return OutboundTestResult(success=False, mode="http", error=f"Xray process exited: {tail or proc.returncode}")
        return _poll_observatory_result(proc, metrics_port, tag)
    except Exception as err:
        return OutboundTestResult(success=False, mode="http", error=str(err))
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        if config_path:
            try:
                os.remove(config_path)
            except OSError:
                pass
        HTTP_TEST_LOCK.release()


def _test_outbound_http(
    outbound: dict[str, Any],
    all_outbounds: list[dict[str, Any]],
    test_url: str,
) -> OutboundTestResult:
    last = OutboundTestResult(success=False, mode="http", error="HTTP probe failed")
    for probe_url in _probe_urls(test_url):
        result = _test_outbound_http_once(outbound, all_outbounds, probe_url)
        if result.success:
            return result
        last = result
    return last
