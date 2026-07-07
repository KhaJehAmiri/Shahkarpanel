"""TCP outbound reachability test from the node host."""
from __future__ import annotations

import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any


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
    elif protocol == "freedom":
        out.append("1.1.1.1:443")
    elif protocol == "dns":
        out.append("1.1.1.1:53")
    return out


def probe_tcp_endpoint(endpoint: str, timeout: float = 5.0) -> dict[str, Any]:
    host, _, port_str = endpoint.rpartition(":")
    result = {"address": endpoint, "success": False, "delay": 0}
    try:
        port = int(port_str)
    except ValueError:
        result["error"] = "invalid port"
        return result
    start = time.time()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            result["success"] = True
            result["delay"] = max(1, int((time.time() - start) * 1000))
    except OSError as err:
        result["error"] = str(err)
        result["delay"] = max(1, int((time.time() - start) * 1000))
    return result


def test_outbound_tcp(outbound: dict[str, Any]) -> dict[str, Any]:
    endpoints = extract_outbound_endpoints(outbound)
    if not endpoints:
        return {"success": False, "mode": "remote-tcp", "error": "No testable endpoint"}

    results = []
    with ThreadPoolExecutor(max_workers=min(4, len(endpoints))) as pool:
        futures = {pool.submit(probe_tcp_endpoint, ep): ep for ep in endpoints}
        for fut in as_completed(futures):
            results.append(fut.result())

    best = min((r["delay"] for r in results if r.get("success")), default=-1)
    first_err = next((r.get("error") for r in results if not r.get("success") and r.get("error")), "")
    out = {"success": best >= 0, "mode": "remote-tcp", "endpoints": results}
    if best >= 0:
        out["delay"] = best
    else:
        out["error"] = first_err or "All endpoints unreachable"
    return out
