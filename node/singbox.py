"""Native sing-box engine management for a Shahkar node.

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
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

logger = logging.getLogger("shahkar-node-singbox")

# Protocols this engine serves. Kept narrow on purpose; everything else stays
# on Xray.
SUPPORTED_TYPES = ("hysteria2", "tuic", "anytls")
QUIC_TYPES = ("hysteria2", "tuic")


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
    type: str                      # "hysteria2" | "tuic" | "anytls"
    tag: str
    listen_port: int
    users: List[SingBoxUser] = field(default_factory=list)
    listen: str = "::"
    # TLS material (paths on the node) — required for both hysteria2 and tuic.
    certificate_path: Optional[str] = None
    key_path: Optional[str] = None
    # Protocol extras
    congestion_control: str = "bbr"          # tuic
    up_mbps: Optional[int] = None            # hysteria2 (legacy brutal; avoid)
    down_mbps: Optional[int] = None          # hysteria2
    obfs_password: Optional[str] = None      # hysteria2 (salamander)
    ignore_client_bandwidth: bool = False    # hysteria2 → BBR on clients
    heartbeat: Optional[str] = None          # tuic
    auth_timeout: Optional[str] = None       # tuic
    zero_rtt_handshake: Optional[bool] = None  # tuic
    udp_timeout: Optional[str] = None
    reuse_addr: Optional[bool] = None

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
            ignore_client_bandwidth=bool(d.get("ignore_client_bandwidth")),
            heartbeat=d.get("heartbeat"),
            auth_timeout=d.get("auth_timeout"),
            zero_rtt_handshake=d.get("zero_rtt_handshake"),
            udp_timeout=d.get("udp_timeout"),
            reuse_addr=d.get("reuse_addr"),
        )


@dataclass
class SingBoxSpec:
    inbounds: List[SingBoxInbound] = field(default_factory=list)
    traffic_limits: List[dict] = field(default_factory=list)
    tunnel_outbounds: List[dict] = field(default_factory=list)
    tunnel_route_rules: List[dict] = field(default_factory=list)
    tunnel_route_final: Optional[str] = None
    clash_api_port: int = 9095
    clash_api_secret: str = ""
    v2ray_api_port: int = 0
    log_level: str = "warn"

    @classmethod
    def from_dict(cls, data: dict) -> "SingBoxSpec":
        clash_port = int(data.get("clash_api_port", 9095))
        v2ray_port = int(data.get("v2ray_api_port") or 0) or (clash_port + 100)
        return cls(
            inbounds=[SingBoxInbound.from_dict(i) for i in (data.get("inbounds") or [])
                      if i.get("type") in SUPPORTED_TYPES],
            traffic_limits=list(data.get("traffic_limits") or []),
            tunnel_outbounds=list(data.get("tunnel_outbounds") or []),
            tunnel_route_rules=list(data.get("tunnel_route_rules") or []),
            tunnel_route_final=data.get("tunnel_route_final"),
            clash_api_port=clash_port,
            clash_api_secret=data.get("clash_api_secret", ""),
            v2ray_api_port=v2ray_port,
            log_level=data.get("log_level", "warn"),
        )


def _tls_block(inbound: SingBoxInbound) -> dict:
    # QUIC inbounds (TUIC / Hysteria2) must advertise h3 or clients that set
    # alpn=h3 fail TLS handshake with "server did not select an ALPN protocol".
    tls: dict = {
        "enabled": True,
        "certificate_path": inbound.certificate_path,
        "key_path": inbound.key_path,
    }
    if inbound.type in QUIC_TYPES:
        tls["alpn"] = ["h3"]
    return tls


def _render_inbound(inbound: SingBoxInbound) -> dict:
    base = {
        "type": inbound.type,
        "tag": inbound.tag,
        "listen": inbound.listen,
        "listen_port": inbound.listen_port,
        "tls": _tls_block(inbound),
    }
    if inbound.udp_timeout:
        base["udp_timeout"] = inbound.udp_timeout
    if inbound.reuse_addr is not None:
        base["reuse_addr"] = inbound.reuse_addr
    if inbound.type == "hysteria2":
        base["users"] = [{"name": u.name, "password": u.password or ""} for u in inbound.users]
        if inbound.up_mbps:
            base["up_mbps"] = inbound.up_mbps
        if inbound.down_mbps:
            base["down_mbps"] = inbound.down_mbps
        if inbound.obfs_password:
            base["obfs"] = {"type": "salamander", "password": inbound.obfs_password}
        if inbound.ignore_client_bandwidth:
            base["ignore_client_bandwidth"] = True
    elif inbound.type == "tuic":
        base["users"] = [
            {"name": u.name, "uuid": u.uuid or "", "password": u.password or ""}
            for u in inbound.users
        ]
        base["congestion_control"] = inbound.congestion_control
        if inbound.heartbeat:
            base["heartbeat"] = inbound.heartbeat
        if inbound.auth_timeout:
            base["auth_timeout"] = inbound.auth_timeout
        if inbound.zero_rtt_handshake is not None:
            base["zero_rtt_handshake"] = inbound.zero_rtt_handshake
    elif inbound.type == "anytls":
        base["users"] = [{"name": u.name, "password": u.password or ""} for u in inbound.users]
    return base


def _supports_v2ray_api(binary: str = "sing-box", run: Optional[Callable] = None) -> bool:
    """Return whether the sing-box binary was built with ``with_v2ray_api``."""
    runner = run or SingBoxManager._default_run
    if not shutil.which(binary):
        return False
    try:
        result = runner([binary, "version"], check=False)
        output = f"{getattr(result, 'stdout', '') or ''}{getattr(result, 'stderr', '') or ''}"
        return "with_v2ray_api" in output
    except Exception:
        return False


def render_config(spec: SingBoxSpec, *, include_v2ray_api: bool = True) -> dict:
    """Render the full sing-box server config (dict, ready to ``json.dump``)."""
    inbound_tags = [i.tag for i in spec.inbounds]
    user_names = sorted({u.name for i in spec.inbounds for u in i.users})
    v2ray_port = spec.v2ray_api_port or (spec.clash_api_port + 100)
    experimental: dict = {
        "clash_api": {
            "external_controller": f"127.0.0.1:{spec.clash_api_port}",
            "secret": spec.clash_api_secret,
        },
        "cache_file": {"enabled": True, "path": "/var/lib/shahkarnode/singbox-cache.db"},
    }
    if inbound_tags and user_names and include_v2ray_api:
        experimental["v2ray_api"] = {
            "listen": f"127.0.0.1:{v2ray_port}",
            "stats": {
                "enabled": True,
                "inbounds": inbound_tags,
                "users": user_names,
            },
        }
    tunnel_final = spec.tunnel_route_final or "direct"
    dns_servers: list = [{"type": "local", "tag": "local"}]
    # When egress is pinned to a tunnel hop, resolve DNS through that hop so
    # lookups cannot leak out the Iran NIC and pull traffic onto ``direct``.
    if tunnel_final != "direct":
        dns_servers.insert(
            0,
            {
                "type": "udp",
                "tag": "tunnel-dns",
                "server": "1.1.1.1",
                "detour": tunnel_final,
            },
        )
    return {
        "log": {"level": spec.log_level, "timestamp": True},
        "dns": {
            "servers": dns_servers,
            "final": "tunnel-dns" if tunnel_final != "direct" else "local",
            "strategy": "prefer_ipv4",
        },
        "inbounds": [_render_inbound(i) for i in spec.inbounds],
        "outbounds": list(spec.tunnel_outbounds) + [
            {
                "type": "direct",
                "tag": "direct",
            },
        ],
        "route": {
            "rules": list(spec.tunnel_route_rules),
            "final": tunnel_final,
            "auto_detect_interface": False,
            "default_domain_resolver": (
                "tunnel-dns" if tunnel_final != "direct" else "local"
            ),
        },
        "experimental": experimental,
    }


def _kill_stale_singbox(
    binary: str = "sing-box",
    config_path: str = "/var/lib/shahkarnode/singbox.json",
    keep_pid: Optional[int] = None,
) -> None:
    """Terminate orphan ``sing-box run -c …`` processes after agent restarts."""
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", f"{binary} run -c {config_path}"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return
    for line in out.strip().splitlines():
        if not line.strip().isdigit():
            continue
        pid = int(line.strip())
        if keep_pid and pid == keep_pid:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except Exception:
            pass
    time.sleep(0.3)


def ensure_self_signed_cert(
    cert_path: Optional[str],
    key_path: Optional[str],
    *,
    common_name: str = "shahkar-node",
    days: int = 3650,
) -> bool:
    """Create a self-signed cert/key pair if either file is missing.

    The panel provisioner normally installs sing-box TLS material during node
    setup (see app/tls/self_signed.py), but a node that was registered outside
    that flow — e.g. imported, or brought up through the SSH-tunnel control
    path — can be missing it. sing-box then refuses to start with a cryptic
    "read certificate: no such file or directory", breaking every QUIC
    protocol on the node. Since the QUIC share links are always issued with
    insecure=1 (clients skip TLS verification, see app/subscription/quic.py),
    a locally generated self-signed cert is sufficient to self-heal here.
    Returns True when a certificate was generated.
    """
    if not cert_path or not key_path:
        return False
    if os.path.isfile(cert_path) and os.path.isfile(key_path):
        return False
    if not shutil.which("openssl"):
        logger.error("cannot self-heal sing-box TLS: openssl not available on node")
        return False
    try:
        for path in (cert_path, key_path):
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
        subprocess.run(
            [
                "openssl", "req", "-x509", "-nodes", "-newkey", "rsa:2048",
                "-keyout", key_path, "-out", cert_path,
                "-days", str(int(days)),
                "-subj", f"/CN={common_name or 'shahkar-node'}",
            ],
            check=True, capture_output=True, text=True,
        )
        os.chmod(cert_path, 0o644)
        os.chmod(key_path, 0o600)
        logger.warning("self-healed missing sing-box TLS cert at %s", cert_path)
        return True
    except Exception as exc:
        logger.error("failed to self-heal sing-box TLS cert %s: %s", cert_path, exc)
        return False


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
        config_path: str = "/var/lib/shahkarnode/singbox.json",
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
        self._v2ray_port = 9195
        self._v2ray_api_supported: Optional[bool] = None
        self._last_check_error = ""

    def _v2ray_api_enabled(self) -> bool:
        if self._v2ray_api_supported is None:
            self._v2ray_api_supported = _supports_v2ray_api(self._binary, run=self._run)
        return bool(self._v2ray_api_supported)

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
        cfg = render_config(spec, include_v2ray_api=self._v2ray_api_enabled())
        os.makedirs(os.path.dirname(self._config_path), exist_ok=True)
        with open(self._config_path, "w") as f:
            json.dump(cfg, f, indent=2)
        return cfg

    def check_config(self) -> bool:
        result = self._run([self._binary, "check", "-c", self._config_path], check=False)
        ok = getattr(result, "returncode", 1) == 0
        self._last_check_error = ""
        if not ok:
            err = (getattr(result, "stderr", "") or getattr(result, "stdout", "") or "").strip()
            self._last_check_error = err
            if err:
                logger.error("sing-box config check failed: %s", err)
        return ok

    def apply(self, spec: SingBoxSpec) -> None:
        """Bring sing-box to the desired state (idempotent restart)."""
        self._clash_port = spec.clash_api_port
        self._clash_secret = spec.clash_api_secret
        self._v2ray_port = spec.v2ray_api_port or (spec.clash_api_port + 100)
        self.write_config(spec)
        # No inbounds → ensure the engine is stopped rather than running idle.
        if not spec.inbounds:
            self.stop()
            return
        # Self-heal missing TLS material before the config check so a node that
        # never got provisioned certs still comes up (QUIC links use insecure=1).
        for ib in spec.inbounds:
            ensure_self_signed_cert(
                getattr(ib, "certificate_path", None),
                getattr(ib, "key_path", None),
            )
        if not self.check_config():
            logger.error("sing-box config invalid; refusing restart")
            detail = getattr(self, "_last_check_error", "") or ""
            raise RuntimeError(
                f"sing-box config check failed: {detail}" if detail
                else "sing-box config check failed"
            )
        self.restart()
        try:
            from speed_limit import SpeedLimitManager, port_limits_from_spec, tune_udp_quic_stack

            if any(ib.type in QUIC_TYPES for ib in spec.inbounds):
                tune_udp_quic_stack()
            limits = port_limits_from_spec({"traffic_limits": spec.traffic_limits})
            if limits:
                SpeedLimitManager().apply_ports(limits)
        except Exception as exc:
            logger.warning("sing-box port speed limits not applied: %s", exc)
        logger.info("Applied sing-box spec (%d inbounds)", len(spec.inbounds))

    def restart(self) -> None:
        self.stop()
        _kill_stale_singbox(binary=self._binary, config_path=self._config_path)
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
        """Per-user interval bytes via sing-box V2Ray API (reset-on-read)."""
        from v2ray_stats import query_user_transfer

        try:
            out = query_user_transfer("127.0.0.1", self._v2ray_port, reset=True)
            if out:
                return out
        except Exception:
            pass
        # Legacy nodes without with_v2ray_api — best-effort active connections only.
        secret = f"?secret={self._clash_secret}" if self._clash_secret else ""
        url = f"http://127.0.0.1:{self._clash_port}/connections{secret}"
        try:
            payload = self._http_get(url)
        except Exception:
            return {}
        return parse_clash_connections(payload)
