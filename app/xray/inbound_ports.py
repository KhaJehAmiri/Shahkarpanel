"""Inbound port validation and Xray bind-failure diagnostics."""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Any

SYSTEM_TAGS = frozenset({"API_INBOUND", "TUNNEL_IN", "TUNNEL_OUT"})

# Known panel services — only flagged when something else is listening.
PANEL_SERVICE_HINTS: dict[int, str] = {
    80: "HTTP (nginx)",
    443: "HTTPS (nginx / panel web)",
    8000: "Panel API (uvicorn)",
}

_BIND_PORT_RE = re.compile(
    r"failed to listen (?:TCP|UDP) on (\d+)|listen tcp [^:]+:(\d+): bind",
    re.I,
)


@dataclass
class PortIssue:
    port: int
    inbound_tag: str | None
    kind: str  # duplicate | in_use
    detail: str


def is_product_inbound(ib: dict[str, Any]) -> bool:
    tag = str(ib.get("tag") or "").strip()
    proto = ib.get("protocol")
    if not tag or tag in SYSTEM_TAGS:
        return False
    if proto == "dokodemo-door" and tag == "API_INBOUND":
        return False
    return bool(proto)


def is_user_assignable_inbound(ib: dict[str, Any]) -> bool:
    """True for panel inbounds that billable users can be assigned to.

  Excludes tunnel capture/exit fragments, dokodemo relays, and the API inbound
  so infrastructure listeners do not trip user-facing billing guards.
    """
    if not is_product_inbound(ib):
        return False
    tag = str(ib.get("tag") or "").strip()
    if tag.startswith("tunnel-"):
        return False
    proto = str(ib.get("protocol") or "").lower()
    if proto in ("dokodemo-door",):
        return False
    from app.models.proxy import ProxyTypes

    if proto == "wireguard":
        return True
    try:
        ProxyTypes(proto)
        return True
    except ValueError:
        return False


def inbound_port(ib: dict[str, Any]) -> int | None:
    raw = ib.get("port")
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw if 1 <= raw <= 65535 else None
    s = str(raw).strip()
    if s.isdigit():
        n = int(s)
        return n if 1 <= n <= 65535 else None
    return None


def listener_pids_by_port() -> dict[int, list[tuple[str, int | None]]]:
    """Map TCP port -> [(process_name, pid), ...] from ``ss -tlnp``."""
    out: dict[int, list[tuple[str, int | None]]] = {}
    try:
        proc = subprocess.run(
            ["ss", "-tlnpH"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return out
    if proc.returncode != 0:
        return out
    for line in proc.stdout.splitlines():
        port_m = re.search(r":(\d+)\s", line)
        if not port_m:
            continue
        port = int(port_m.group(1))
        users_m = re.search(r"users:\(\((.*)\)\)", line)
        if not users_m:
            out.setdefault(port, []).append(("unknown", None))
            continue
        users_blob = users_m.group(1)
        for chunk in users_blob.split("),("):
            chunk = chunk.strip('"')
            name_m = re.match(r"\"?([^\",]+)\"?", chunk)
            pid_m = re.search(r"pid=(\d+)", chunk)
            name = name_m.group(1) if name_m else "unknown"
            pid = int(pid_m.group(1)) if pid_m else None
            out.setdefault(port, []).append((name, pid))
    return out


def _tcp_listeners() -> dict[int, str]:
    """Map port -> process name for TCP listeners (best effort)."""
    out: dict[int, str] = {}
    for port, entries in listener_pids_by_port().items():
        if entries:
            out[port] = entries[0][0]
        else:
            out[port] = "unknown"
    return out


def product_inbound_ports(inbounds: list[dict[str, Any]] | None) -> list[int]:
    ports: list[int] = []
    seen: set[int] = set()
    for ib in inbounds or []:
        if not isinstance(ib, dict) or not is_product_inbound(ib):
            continue
        if is_loopback_inbound(ib):
            continue
        port = inbound_port(ib)
        if port is not None and port not in seen:
            seen.add(port)
            ports.append(port)
    return ports


def inbound_listen(ib: dict[str, Any]) -> str:
    listen = str(ib.get("listen") or "0.0.0.0").strip()
    return listen or "0.0.0.0"


def is_loopback_inbound(ib: dict[str, Any]) -> bool:
    listen = inbound_listen(ib).lower()
    return listen in ("127.0.0.1", "localhost", "::1")


def _stdin_xray_pids() -> frozenset[int]:
    try:
        from config import XRAY_EXECUTABLE_PATH
        from app.xray.core import find_stdin_xray_pids

        return frozenset(find_stdin_xray_pids(XRAY_EXECUTABLE_PATH))
    except Exception:
        return frozenset()


def _port_held_by_stdin_xray(port: int, stdin_pids: frozenset[int]) -> bool:
    """True when an existing stdin Xray process already listens on ``port``."""
    if not stdin_pids:
        return False
    entries = listener_pids_by_port().get(port, [])
    if not entries:
        return False
    for _name, pid in entries:
        if pid is not None and pid in stdin_pids:
            return True
    # ``ss -tlnp`` often omits pid/name in minimal containers; treat unknown-only as Xray.
    return all(name.lower() in ("unknown", "xray") for name, _ in entries)


def collect_port_issues(
    inbounds: list[dict[str, Any]],
    *,
    ignore_processes: frozenset[str] = frozenset({"xray"}),
) -> list[PortIssue]:
    """Return port problems that would prevent Xray from starting."""
    issues: list[PortIssue] = []
    listeners = _tcp_listeners()
    stdin_pids = _stdin_xray_pids()
    configured_ports = set(product_inbound_ports(inbounds))
    port_to_tags: dict[int, list[str]] = {}
    tag_to_inbound: dict[str, dict[str, Any]] = {}

    for ib in inbounds or []:
        if not isinstance(ib, dict) or not is_product_inbound(ib):
            continue
        tag = str(ib.get("tag") or "")
        port = inbound_port(ib)
        if port is None:
            continue
        tag_to_inbound[tag] = ib
        port_to_tags.setdefault(port, []).append(tag)

    for port, tags in port_to_tags.items():
        if len(tags) > 1:
            for tag in tags[1:]:
                issues.append(
                    PortIssue(
                        port=port,
                        inbound_tag=tag,
                        kind="duplicate",
                        detail=f'Port {port} is used by both "{tags[0]}" and "{tag}"',
                    )
                )
            continue

        tag = tags[0]
        ib = tag_to_inbound.get(tag) or {}
        if is_loopback_inbound(ib):
            continue

        owner = listeners.get(port)
        if owner and owner.lower() not in ignore_processes:
            if (
                owner.lower() == "unknown"
                and port in configured_ports
                and _port_held_by_stdin_xray(port, stdin_pids)
            ):
                continue
            hint = PANEL_SERVICE_HINTS.get(port, owner)
            if port == 443:
                detail = (
                    f'Port 443 is already used by {hint}. '
                    "Use a CDN subscription host (domain:443 with a different inbound port) "
                    "so nginx terminates TLS, or free port 443 for direct Xray binding."
                )
            else:
                detail = f"Port {port} is already in use by {hint} ({owner})"
            issues.append(
                PortIssue(
                    port=port,
                    inbound_tag=tag,
                    kind="in_use",
                    detail=detail,
                )
            )

    return issues


def format_port_issues(issues: list[PortIssue]) -> str:
    if not issues:
        return ""
    parts = []
    for issue in issues:
        tag = f' inbound "{issue.inbound_tag}"' if issue.inbound_tag else ""
        parts.append(f"{issue.detail}{tag}.")
    return " ".join(parts)


def find_inbound_tag_for_port(
    inbounds: list[dict[str, Any]] | None,
    port: int,
) -> str | None:
    if not inbounds:
        return None
    for ib in inbounds:
        if isinstance(ib, dict) and inbound_port(ib) == port:
            tag = ib.get("tag")
            if tag:
                return str(tag)
    return None


def parse_bind_failure(
    log_lines: list[str] | str,
    inbounds: list[dict[str, Any]] | None = None,
) -> tuple[int | None, str | None, str]:
    """Extract (port, inbound_tag, message) from Xray startup failure logs."""
    text = log_lines if isinstance(log_lines, str) else "\n".join(log_lines)
    port: int | None = None
    for m in _BIND_PORT_RE.finditer(text):
        port = int(m.group(1) or m.group(2))
        break
    if port is None:
        for line in reversed(text.splitlines()):
            if "Failed to start" in line or "bind" in line.lower():
                return None, None, line.strip()
        return None, None, "Xray failed to start"

    tag = find_inbound_tag_for_port(inbounds, port)
    hint = PANEL_SERVICE_HINTS.get(port)
    if hint and port == 443:
        msg = (
            f'Inbound failed to bind port 443 ({hint}). '
            "Port 443 must be free for proxy listeners, or use another port."
        )
    elif hint:
        msg = f"Inbound failed to bind port {port} ({hint} is already listening)."
    else:
        msg = f"Inbound failed to bind port {port} (address already in use)."
    if tag:
        msg = f'{msg} Check inbound "{tag}".'
    return port, tag, msg
