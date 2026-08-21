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
import hashlib
import json
import logging
import os
import shutil
import signal
import subprocess
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set

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
    # When egress is pinned to a tunnel hop, keep a tunneled resolver for
    # explicit DNS queries so lookups cannot leak out the Iran NIC.
    # Do *not* set default_domain_resolver: that pre-resolves Hysteria/TUIC
    # destinations to IPs and Xray's domain→WARP list never matches (VLESS
    # still works because it sends the hostname in-protocol).
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
    route: dict = {
        "rules": list(spec.tunnel_route_rules),
        "final": tunnel_final,
        "auto_detect_interface": False,
    }
    # Keep a resolver tag available for DNS queries; destinations themselves
    # stay domains so SOCKS/Xray can apply the sensitive WARP split.
    if tunnel_final == "direct":
        route["default_domain_resolver"] = "local"
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
        "route": route,
        "experimental": experimental,
    }


def _config_fingerprint(cfg: dict) -> str:
    """Order-insensitive digest of a rendered config.

    User lists arrive in whatever order the panel's query produced, so a plain
    text compare would report a change on every sync and restart the engine.
    """
    try:
        snapshot = json.loads(json.dumps(cfg))
    except (TypeError, ValueError):
        return ""
    for inbound in snapshot.get("inbounds") or []:
        users = inbound.get("users")
        if isinstance(users, list):
            inbound["users"] = sorted(
                users, key=lambda u: json.dumps(u, sort_keys=True) if isinstance(u, dict) else str(u)
            )
    stats = ((snapshot.get("experimental") or {}).get("v2ray_api") or {}).get("stats") or {}
    for key in ("users", "inbounds", "outbounds"):
        if isinstance(stats.get(key), list):
            stats[key] = sorted(str(v) for v in stats[key])
    return hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _running_singbox_pids(binary: str, config_path: str) -> List[int]:
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", f"{binary} run -c {config_path}"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [int(line.strip()) for line in out.strip().splitlines() if line.strip().isdigit()]


def _kill_stale_singbox(
    binary: str = "sing-box",
    config_path: str = "/var/lib/shahkarnode/singbox.json",
    keep_pid: Optional[int] = None,
) -> None:
    """Terminate orphan ``sing-box run -c …`` processes after agent restarts."""
    for pid in _running_singbox_pids(binary, config_path):
        if keep_pid and pid == keep_pid:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except Exception:
            pass
    time.sleep(0.3)


def _looks_like_ip(value: str) -> bool:
    import ipaddress

    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


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
        name = common_name or "shahkar-node"
        san = f"IP:{name}" if _looks_like_ip(name) else f"DNS:{name}"
        subprocess.run(
            [
                "openssl", "req", "-x509", "-nodes", "-newkey", "rsa:2048",
                "-keyout", key_path, "-out", cert_path,
                "-days", str(int(days)),
                "-subj", f"/CN={name}",
                # No SAN means the cert matches no name at all, so any client
                # that verifies rejects the handshake.
                "-addext", f"subjectAltName={san}",
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


def _connection_user(conn: dict) -> str:
    """Inbound user name as Clash/sing-box actually tags it.

    Stock ``metadata.user`` is often empty for AnyTLS/Hy2 (Karing). Newer
    clash-api builds put the same identity on ``inboundUser`` / ``sourceUser``.
    """
    meta = conn.get("metadata") or {}
    for key in ("user", "inboundUser", "sourceUser"):
        val = meta.get(key) or conn.get(key)
        if val:
            return str(val)
    return ""


def parse_clash_connections(payload: dict) -> Dict[str, dict]:
    """Aggregate Clash ``/connections`` upload/download bytes per user name.

    sing-box tags each connection with the matched inbound user; we sum bytes
    per ``user`` so the panel can map ``name -> User.id``.
    """
    result: Dict[str, dict] = {}
    for conn in (payload or {}).get("connections", []) or []:
        user = _connection_user(conn)
        if not user:
            continue
        entry = result.setdefault(user, {"rx": 0, "tx": 0})
        entry["rx"] += int(conn.get("download", 0) or 0)
        entry["tx"] += int(conn.get("upload", 0) or 0)
    return result


def normalize_identifiers(names) -> Set[str]:
    return {str(n).strip() for n in (names or []) if str(n).strip()}


def connection_matches(conn: dict, identifiers: Set[str]) -> bool:
    """True when a Clash connection belongs to one of the given identities."""
    if not identifiers:
        return False
    user = _connection_user(conn)
    if not user:
        return False
    if user in identifiers:
        return True
    if "." in user and user.split(".", 1)[1] in identifiers:
        return True
    return False


def user_entry_matches(entry: dict, identifiers: Set[str]) -> bool:
    if not identifiers:
        return False
    name = str((entry or {}).get("name") or "")
    if name in identifiers:
        return True
    if "." in name and name.split(".", 1)[1] in identifiers:
        return True
    password = str((entry or {}).get("password") or "")
    uuid = str((entry or {}).get("uuid") or "")
    return bool(password and password in identifiers) or bool(uuid and uuid in identifiers)


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
        self._http_delete = self._default_http_delete
        self._proc: Optional[subprocess.Popen] = None
        self._clash_port = 9095
        self._clash_secret = ""
        self._v2ray_port = 9195
        self._v2ray_api_supported: Optional[bool] = None
        self._last_check_error = ""
        self._apply_lock = threading.Lock()
        self._pending_spec: Optional[SingBoxSpec] = None
        self._pending_restart = False
        self._apply_thread: Optional[threading.Thread] = None
        self._apply_generation = 0
        self._revoked_names: Set[str] = set()
        self._config_unchanged = False

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

    @staticmethod
    def _default_http_delete(url: str, timeout: float = 4.0) -> None:
        req = urllib.request.Request(url, method="DELETE")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()

    def _clash_url(self, path: str = "/connections") -> str:
        secret = f"?secret={self._clash_secret}" if self._clash_secret else ""
        return f"http://127.0.0.1:{self._clash_port}{path}{secret}"

    def available(self) -> bool:
        return shutil.which(self._binary) is not None

    def write_config(self, spec: SingBoxSpec) -> dict:
        cfg = render_config(spec, include_v2ray_api=self._v2ray_api_enabled())
        os.makedirs(os.path.dirname(self._config_path), exist_ok=True)
        self._config_unchanged = _config_fingerprint(cfg) == self._on_disk_fingerprint()
        with open(self._config_path, "w") as f:
            json.dump(cfg, f, indent=2)
        return cfg

    def _on_disk_fingerprint(self) -> str:
        try:
            with open(self._config_path, "r") as f:
                return _config_fingerprint(json.load(f))
        except Exception:
            return ""

    def _engine_alive(self) -> bool:
        if self._proc is not None and self._proc.poll() is None:
            return True
        return _running_singbox_pids(self._binary, self._config_path) != []

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

    def apply(self, spec: SingBoxSpec, generation: Optional[int] = None) -> None:
        """Bring sing-box to the desired state.

        The panel re-pushes the whole spec after *any* user mutation, and on a
        busy panel that is every debounce window. sing-box has no live user
        reload, so each apply used to recycle the process: every AnyTLS /
        Hysteria2 / TUIC tunnel dropped and the v2ray-api counters reset before
        the next usage poll could read them — a client stayed "connected" while
        nothing was billed and ``online_at`` never moved. An apply that renders
        byte-identical config now leaves the running engine alone.
        """
        self._clash_port = spec.clash_api_port
        self._clash_secret = spec.clash_api_secret
        self._v2ray_port = spec.v2ray_api_port or (spec.clash_api_port + 100)
        with self._apply_lock:
            if generation is not None and generation != self._apply_generation:
                return
            self._config_unchanged = False
            revoked = set(self._revoked_names)
            if revoked:
                for inbound in spec.inbounds:
                    inbound.users = [
                        u
                        for u in inbound.users
                        if not user_entry_matches(
                            {"name": u.name, "password": u.password, "uuid": u.uuid},
                            revoked,
                        )
                    ]
            self.write_config(spec)
            if generation is not None and generation != self._apply_generation:
                return
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
        with self._apply_lock:
            if generation is not None and generation != self._apply_generation:
                return
            unchanged = self._config_unchanged
        if unchanged and self._engine_alive():
            logger.info("sing-box config unchanged; keeping live sessions")
        else:
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

    def schedule_apply(self, spec: SingBoxSpec) -> None:
        """Queue a full apply and return immediately.

        An 8k-user spec + ``sing-box check`` + restart routinely exceeds the
        panel's 15s RPyC timeout. Holding that RPC until restart finished
        marked the apply as failed, retried it, and kept the node lock so
        ``singbox_transfer`` (billing) and disable-kicks were skipped.
        """
        with self._apply_lock:
            self._pending_spec = spec
            self._kick_apply_thread()

    def schedule_restart(self) -> None:
        with self._apply_lock:
            self._pending_restart = True
            self._kick_apply_thread()

    def _kick_apply_thread(self) -> None:
        t = self._apply_thread
        if t is not None and t.is_alive():
            return
        t = threading.Thread(target=self._apply_loop, name="singbox-apply", daemon=True)
        self._apply_thread = t
        t.start()

    def _apply_loop(self) -> None:
        while True:
            with self._apply_lock:
                spec = self._pending_spec
                self._pending_spec = None
                restart_only = self._pending_restart
                self._pending_restart = False
                generation = self._apply_generation
            if spec is None and not restart_only:
                return
            try:
                if spec is not None:
                    self.apply(spec, generation=generation)
                    with self._apply_lock:
                        if generation != self._apply_generation:
                            continue
                elif restart_only:
                    self.restart()
            except Exception:
                logger.exception("scheduled sing-box apply/restart failed")

    def kick_users(self, names) -> int:
        """Close Clash connections whose inbound user matches ``names``."""
        identifiers = normalize_identifiers(names)
        if not identifiers:
            return 0
        try:
            try:
                payload = self._http_get(self._clash_url("/connections"), timeout=4.0)
            except TypeError:
                payload = self._http_get(self._clash_url("/connections"))
        except Exception:
            logger.debug("sing-box clash connections read failed", exc_info=True)
            return 0
        kicked = 0
        for conn in (payload or {}).get("connections") or []:
            if not connection_matches(conn, identifiers):
                continue
            cid = conn.get("id")
            if not cid:
                continue
            try:
                self._http_delete(self._clash_url(f"/connections/{cid}"), timeout=4.0)
                kicked += 1
            except Exception:
                logger.debug("sing-box kick %s failed", cid, exc_info=True)
        if kicked:
            logger.info("kicked %s sing-box connections", kicked)
        return kicked

    def _strip_users_from_config(self, identifiers: Set[str]) -> int:
        if not identifiers or not os.path.isfile(self._config_path):
            return 0
        try:
            with open(self._config_path, "r") as f:
                cfg = json.load(f)
        except Exception:
            logger.debug("sing-box config read for revoke failed", exc_info=True)
            return 0
        removed = 0
        for inbound in cfg.get("inbounds") or []:
            users = inbound.get("users") or []
            if not isinstance(users, list) or not users:
                continue
            keep = []
            for entry in users:
                if isinstance(entry, dict) and user_entry_matches(entry, identifiers):
                    removed += 1
                    continue
                keep.append(entry)
            inbound["users"] = keep
        stats = (
            ((cfg.get("experimental") or {}).get("v2ray_api") or {}).get("stats") or {}
        )
        stats_users = stats.get("users")
        if isinstance(stats_users, list):
            keep_names = []
            for name in stats_users:
                text = str(name or "")
                drop = text in identifiers or (
                    "." in text and text.split(".", 1)[1] in identifiers
                )
                if drop:
                    removed += 1
                    continue
                keep_names.append(name)
            stats["users"] = keep_names
        if not removed:
            return 0
        try:
            with open(self._config_path, "w") as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            logger.exception("sing-box config write for revoke failed")
            return 0
        return removed

    def _strip_pending_spec(self, identifiers: Set[str]) -> int:
        spec = self._pending_spec
        if spec is None or not identifiers:
            return 0
        removed = 0
        for inbound in spec.inbounds:
            keep = []
            for user in inbound.users:
                fake = {"name": user.name, "password": user.password, "uuid": user.uuid}
                if user_entry_matches(fake, identifiers):
                    removed += 1
                    continue
                keep.append(user)
            inbound.users = keep
        return removed

    def revoke_users(self, names) -> dict:
        """Drop live sessions and stop the user being able to reconnect.

        Clash ``DELETE /connections/{id}`` cuts the current tunnel immediately.
        The on-disk user list is then stripped and sing-box is restarted so a
        reconnect cannot authenticate. Restart is scheduled so this RPC does
        not sit on the panel lock for the whole process recycle.
        """
        identifiers = normalize_identifiers(names)
        kicked = self.kick_users(identifiers)
        if not identifiers:
            return {"kicked": kicked, "removed": 0}
        with self._apply_lock:
            self._revoked_names |= identifiers
            self._apply_generation += 1
            removed = self._strip_pending_spec(identifiers)
            removed += self._strip_users_from_config(identifiers)
            if removed:
                self._pending_restart = True
                self._kick_apply_thread()
        return {"kicked": kicked, "removed": removed}

    def unrevoke_users(self, names) -> int:
        identifiers = normalize_identifiers(names)
        if not identifiers:
            return 0
        with self._apply_lock:
            before = len(self._revoked_names)
            self._revoked_names -= identifiers
            return before - len(self._revoked_names)

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

    def engine_epoch(self) -> str:
        """Identity of the running process, so the panel can tell a counter
        reset (engine recycled, counters back to zero) from its own restart."""
        pids = _running_singbox_pids(self._binary, self._config_path)
        if self._proc is not None and self._proc.poll() is None:
            pids = [self._proc.pid] + [p for p in pids if p != self._proc.pid]
        if not pids:
            return ""
        pid = pids[0]
        try:
            with open(f"/proc/{pid}/stat", "r") as f:
                started = f.read().rsplit(")", 1)[1].split()[19]
        except Exception:
            started = "0"
        return f"{pid}:{started}"

    def get_transfer(self) -> Dict[str, dict]:
        """Per-user bytes. Both V2Ray API and Clash are cumulative here.

        Clash ``/connections`` on this binary never marshals ``metadata.user``
        (sing-box 1.13 tracker.go). V2Ray API does count when ``metadata.User``
        is set. Never ``reset=True``: a partial QueryStats plus reset used to
        throw away users that were not in the returned map. The panel diffs
        ``__source__=cumulative`` the same way as Clash, keyed on
        ``__epoch__`` so a recycled engine does not silently rebaseline.
        """
        from v2ray_stats import query_user_transfer

        v2ray: Dict[str, dict] = {}
        try:
            v2ray = query_user_transfer(
                "127.0.0.1", self._v2ray_port, reset=False, timeout=12.0
            ) or {}
        except Exception:
            v2ray = {}
        clash: Dict[str, dict] = {}
        try:
            payload = self._http_get(self._clash_url("/connections"), timeout=4.0)
            clash = parse_clash_connections(payload)
        except Exception:
            clash = {}
        merged = dict(v2ray)
        for name, counters in clash.items():
            if not name or name.startswith("__"):
                continue
            cur = merged.get(name) or {"rx": 0, "tx": 0}
            merged[name] = {
                "rx": max(int(cur.get("rx") or 0), int((counters or {}).get("rx") or 0)),
                "tx": max(int(cur.get("tx") or 0), int((counters or {}).get("tx") or 0)),
            }
        if not merged:
            return {}
        return {"__source__": "cumulative", "__epoch__": self.engine_epoch(), **merged}
