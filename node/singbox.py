"""Native sing-box engine management for a NexusPanel node.

sing-box is the node's *second* data-plane engine (alongside Xray), used for
QUIC-based protocols Xray cannot serve: Hysteria2 and TUIC. Like the WireGuard
module, the panel pushes a declarative spec (inbounds + their user lists) and
reads back per-user traffic counters that the panel folds into the single
``User.used_traffic`` (see ``docs/accounting-contract.md``).

The module is deliberately self-contained (stdlib only) and the command/HTTP
runners are injectable so config rendering and stats parsing stay unit-testable
without root or a real sing-box binary.
"""
import json
import logging
import os
import shutil
import signal
import subprocess
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

logger = logging.getLogger("nexus-node-singbox")

# Protocols this engine serves. Kept narrow on purpose; everything else stays
# on Xray.
SUPPORTED_TYPES = ("hysteria2", "tuic")


@dataclass
class SingBoxUser:
    # ``name`` is the panel email (``<user_id>.<username>``) so traffic maps back.
    name: str
    password: Optional[str] = None
    uuid: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "SingBoxUser":
        return cls(name=d["name"], password=d.get("password"), uuid=d.get("uuid"))


@dataclass
class SingBoxInbound:
    type: str                      # "hysteria2" | "tuic"
    tag: str
    listen_port: int
    users: List[SingBoxUser] = field(default_factory=list)
    listen: str = "::"
    # TLS material (paths on the node) — required for both hysteria2 and tuic.
    certificate_path: Optional[str] = None
    key_path: Optional[str] = None
    # Protocol extras
    congestion_control: str = "bbr"          # tuic
    up_mbps: Optional[int] = None            # hysteria2
    down_mbps: Optional[int] = None          # hysteria2
    obfs_password: Optional[str] = None      # hysteria2 (salamander)

    @classmethod
    def from_dict(cls, d: dict) -> "SingBoxInbound":
        return cls(
            type=d["type"],
            tag=d["tag"],
            listen_port=int(d["listen_port"]),
            users=[SingBoxUser.from_dict(u) for u in (d.get("users") or [])],
            listen=d.get("listen", "::"),
            certificate_path=d.get("certificate_path"),
            key_path=d.get("key_path"),
            congestion_control=d.get("congestion_control", "bbr"),
            up_mbps=d.get("up_mbps"),
            down_mbps=d.get("down_mbps"),
            obfs_password=d.get("obfs_password") or None,
        )


@dataclass
class SingBoxSpec:
    inbounds: List[SingBoxInbound] = field(default_factory=list)
    # Local Clash API used to read per-user traffic counters.
    clash_api_port: int = 9095
    clash_api_secret: str = ""
    log_level: str = "warn"

    @classmethod
    def from_dict(cls, data: dict) -> "SingBoxSpec":
        return cls(
            inbounds=[SingBoxInbound.from_dict(i) for i in (data.get("inbounds") or [])
                      if i.get("type") in SUPPORTED_TYPES],
            clash_api_port=int(data.get("clash_api_port", 9095)),
            clash_api_secret=data.get("clash_api_secret", ""),
            log_level=data.get("log_level", "warn"),
        )


def _tls_block(inbound: SingBoxInbound) -> dict:
    return {
        "enabled": True,
        "certificate_path": inbound.certificate_path,
        "key_path": inbound.key_path,
    }


def _render_inbound(inbound: SingBoxInbound) -> dict:
    base = {
        "type": inbound.type,
        "tag": inbound.tag,
        "listen": inbound.listen,
        "listen_port": inbound.listen_port,
        "tls": _tls_block(inbound),
    }
    if inbound.type == "hysteria2":
        base["users"] = [{"name": u.name, "password": u.password or ""} for u in inbound.users]
        if inbound.up_mbps:
            base["up_mbps"] = inbound.up_mbps
        if inbound.down_mbps:
            base["down_mbps"] = inbound.down_mbps
        if inbound.obfs_password:
            base["obfs"] = {"type": "salamander", "password": inbound.obfs_password}
    elif inbound.type == "tuic":
        base["users"] = [
            {"name": u.name, "uuid": u.uuid or "", "password": u.password or ""}
            for u in inbound.users
        ]
        base["congestion_control"] = inbound.congestion_control
    return base


def render_config(spec: SingBoxSpec) -> dict:
    """Render the full sing-box server config (dict, ready to ``json.dump``)."""
    return {
        "log": {"level": spec.log_level, "timestamp": True},
        "inbounds": [_render_inbound(i) for i in spec.inbounds],
        "outbounds": [{"type": "direct", "tag": "direct"}],
        # Clash API exposes connection/traffic counters we poll per user tag.
        "experimental": {
            "clash_api": {
                "external_controller": f"127.0.0.1:{spec.clash_api_port}",
                "secret": spec.clash_api_secret,
            },
            "cache_file": {"enabled": True, "path": "/var/lib/nexusnode/singbox-cache.db"},
        },
    }


def parse_clash_connections(payload: dict) -> Dict[str, dict]:
    """Aggregate Clash ``/connections`` upload/download bytes per user name.

    sing-box tags each connection with the matched inbound user; we sum bytes
    per ``user`` so the panel can map ``name -> User.id``.
    """
    result: Dict[str, dict] = {}
    for conn in (payload or {}).get("connections", []) or []:
        meta = conn.get("metadata", {}) or {}
        user = meta.get("user") or conn.get("user")
        if not user:
            continue
        entry = result.setdefault(user, {"rx": 0, "tx": 0})
        entry["rx"] += int(conn.get("download", 0) or 0)
        entry["tx"] += int(conn.get("upload", 0) or 0)
    return result


class SingBoxManager:
    """Thin wrapper that renders config, runs sing-box, and reads traffic."""

    def __init__(
        self,
        config_path: str = "/var/lib/nexusnode/singbox.json",
        binary: str = "sing-box",
        run: Optional[Callable] = None,
        http_get: Optional[Callable] = None,
    ):
        self._config_path = config_path
        self._binary = binary
        self._run = run or self._default_run
        self._http_get = http_get or self._default_http_get
        self._proc: Optional[subprocess.Popen] = None
        self._clash_port = 9095
        self._clash_secret = ""

    @staticmethod
    def _default_run(cmd, check=True):
        return subprocess.run(cmd, text=True, capture_output=True, check=check)

    @staticmethod
    def _default_http_get(url: str, timeout: float = 5.0) -> dict:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode())

    def available(self) -> bool:
        return shutil.which(self._binary) is not None

    def write_config(self, spec: SingBoxSpec) -> dict:
        cfg = render_config(spec)
        os.makedirs(os.path.dirname(self._config_path), exist_ok=True)
        with open(self._config_path, "w") as f:
            json.dump(cfg, f, indent=2)
        return cfg

    def check_config(self) -> bool:
        result = self._run([self._binary, "check", "-c", self._config_path], check=False)
        return getattr(result, "returncode", 1) == 0

    def apply(self, spec: SingBoxSpec) -> None:
        """Bring sing-box to the desired state (idempotent restart)."""
        self._clash_port = spec.clash_api_port
        self._clash_secret = spec.clash_api_secret
        self.write_config(spec)
        # No inbounds → ensure the engine is stopped rather than running idle.
        if not spec.inbounds:
            self.stop()
            return
        self.restart()
        logger.info("Applied sing-box spec (%d inbounds)", len(spec.inbounds))

    def restart(self) -> None:
        self.stop()
        self._proc = subprocess.Popen(
            [self._binary, "run", "-c", self._config_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.send_signal(signal.SIGTERM)
            try:
                self._proc.wait(timeout=10)
            except Exception:
                self._proc.kill()
        self._proc = None

    def is_running(self) -> bool:
        return bool(self._proc and self._proc.poll() is None)

    def get_transfer(self) -> Dict[str, dict]:
        """Per-user ``{name: {"rx", "tx"}}`` from the local Clash API."""
        secret = f"?secret={self._clash_secret}" if self._clash_secret else ""
        url = f"http://127.0.0.1:{self._clash_port}/connections{secret}"
        try:
            payload = self._http_get(url)
        except Exception:
            return {}
        return parse_clash_connections(payload)
