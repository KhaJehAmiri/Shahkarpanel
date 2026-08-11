import hashlib
import os
import socket
import re
import ssl
import struct
import tempfile
import threading
import time
from collections import deque
from contextlib import contextmanager
from typing import List

import grpc
import requests
import rpyc
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.poolmanager import PoolManager
from websocket import WebSocketConnectionClosedException, WebSocketTimeoutException, create_connection

from app.xray.config import XRayConfig
from xray_api import XRay as XRayAPI

# How long to wait for a freshly started node core's gRPC API to accept a
# channel. This was 5s, which is fine on a LAN but not on the Iran↔abroad
# control path: the TLS handshake alone costs 200-550ms through the SSH
# tunnel, and a core loading thousands of WireGuard peers needs several
# seconds more before it binds. When the wait expired the panel concluded the
# start had failed, tore the node back to native WireGuard, and the next
# health tick restarted Xray again — a restart loop that dropped every session
# on the node every couple of minutes while Xray was in fact running fine.
NODE_API_READY_TIMEOUT = float(os.environ.get("NODE_API_READY_TIMEOUT", "30"))

# Upper bound for a single blocking send on an RPyC channel. Without it, a node
# that stops draining our socket (dead peer with no RST, saturated tunnel)
# leaves ``SSLSocket.send`` blocking forever *while holding the node lock*, and
# every usage / health / sync job that touches that node piles up behind it
# until the panel looks frozen. Reads keep RPyC's own ``sync_request_timeout``.
NODE_RPYC_SEND_TIMEOUT = float(os.environ.get("NODE_RPYC_SEND_TIMEOUT", "60"))


def _bound_channel_sends(conn, seconds: float = NODE_RPYC_SEND_TIMEOUT) -> None:
    """Apply ``SO_SNDTIMEO`` to an RPyC connection's socket (best effort)."""
    if seconds <= 0:
        return
    try:
        sock = conn._channel.stream.sock
    except Exception:
        return
    whole = int(seconds)
    micro = int((seconds - whole) * 1_000_000)
    try:
        sock.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_SNDTIMEO,
            struct.pack("@ll", whole, micro),
        )
    except Exception:
        pass


def _pem_peer_cert(address: str, port: int, timeout: float = 5.0) -> str:
    """Fetch the peer TLS certificate with a hard socket timeout.

    ``ssl.get_server_certificate`` has no timeout and can block a node's
    ``_lock`` forever when the far end drops SYN — freezing every scheduler
    job that touches that node (Overview stats included).

    Nodes use self-signed certs verified via TOFU pinning (``verify_or_capture_pin``
    right after this call), not a CA trust chain — so, like the original
    ``get_server_certificate``, this must NOT verify the certificate itself
    (an ``ssl.create_default_context()`` would reject every self-signed node
    with CERTIFICATE_VERIFY_FAILED before pinning ever runs).
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with socket.create_connection((address, int(port)), timeout=timeout) as sock:
        with context.wrap_socket(sock) as ssock:
            der = ssock.getpeercert(binary_form=True)
            if not der:
                raise ConnectionError(f"No TLS certificate from {address}:{port}")
            return ssl.DER_cert_to_PEM_cert(der)


def _inline_tls_certificates(config: XRayConfig) -> XRayConfig:
    from app.migration.three_x_ui import _sanitize_migrated_stream_tls

    for inbound in config.get("inbounds", []):
        stream_settings = inbound.get("streamSettings") or {}
        if isinstance(stream_settings, dict):
            _sanitize_migrated_stream_tls(stream_settings)
        tls_settings = stream_settings.get("tlsSettings") or {}
        certificates = tls_settings.get("certificates") or []
        for certificate in certificates:
            if certificate.get("certificateFile"):
                with open(certificate["certificateFile"]) as file:
                    certificate["certificate"] = [line.strip() for line in file.readlines()]
                    del certificate["certificateFile"]

            if certificate.get("keyFile"):
                with open(certificate["keyFile"]) as file:
                    certificate["key"] = [line.strip() for line in file.readlines()]
                    del certificate["keyFile"]
    return config


def string_to_temp_file(content: str):
    file = tempfile.NamedTemporaryFile(mode='w+t')
    file.write(content)
    file.flush()
    return file


def cert_sha256(pem_cert: str) -> str:
    """SHA-256 fingerprint (hex) of a PEM certificate's DER bytes."""
    der = ssl.PEM_cert_to_DER_cert(pem_cert)
    return hashlib.sha256(der).hexdigest()


def verify_or_capture_pin(node_label, pem_cert: str, pinned):
    """Return the observed cert fingerprint, raising on a pin mismatch.

    When ``pinned`` is falsy this is trust-on-first-use (the caller persists the
    returned fingerprint). When set, a mismatch means the node presented a
    different cert than the pinned one — a possible MITM — so we refuse.
    """
    observed = cert_sha256(pem_cert)
    if pinned and str(pinned).lower() != observed.lower():
        raise ConnectionError(
            f"Node {node_label}: TLS cert fingerprint mismatch (pinned "
            f"{str(pinned)[:16]}… got {observed[:16]}…) — possible MITM; refusing to connect."
        )
    return observed


class SANIgnoringAdaptor(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False):
        self.poolmanager = PoolManager(num_pools=connections,
                                       maxsize=maxsize,
                                       block=block,
                                       assert_hostname=False)


class NodeAPIError(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        self.detail = detail


class ReSTXRayNode:
    def __init__(self,
                 address: str,
                 port: int,
                 api_port: int,
                 ssl_key: str,
                 ssl_cert: str,
                 usage_coefficient: float = 1,
                 pinned_cert_sha256: str = None):

        self.address = address
        self.port = port
        self.api_port = api_port
        self.ssl_key = ssl_key
        self.ssl_cert = ssl_cert
        self.usage_coefficient = usage_coefficient
        self.pinned_cert_sha256 = pinned_cert_sha256
        self.observed_cert_sha256 = None

        self._keyfile = string_to_temp_file(ssl_key)
        self._certfile = string_to_temp_file(ssl_cert)

        from config import NODE_SSL_VERIFY

        self._node_ssl_verify = NODE_SSL_VERIFY

        # NODE_SSL_VERIFY only controls *hostname/SAN* matching: node certs are
        # self-signed with no SAN (see node/certificate.py), so strict hostname
        # checking is opt-in for deployments that provision proper CA-issued
        # certs. Regardless of this flag, every channel below still verifies the
        # node's certificate *content* byte-for-byte against the TOFU-pinned
        # fingerprint (see verify_or_capture_pin / connect()) — plain
        # "no verification at all" is never used, so a MITM cannot silently
        # substitute a different cert even with the default (compat) setting.
        self.session = requests.Session()
        if NODE_SSL_VERIFY:
            self.session.verify = True
        else:
            self.session.mount('https://', SANIgnoringAdaptor())
            self.session.verify = False
        self.session.cert = (self._certfile.name, self._keyfile.name)

        self._session_id = None
        self._rest_api_url = f"https://{self.address.strip('/')}:{self.port}"

        self._ssl_context = ssl.create_default_context()
        self._ssl_context.verify_mode = ssl.CERT_REQUIRED
        self._ssl_context.check_hostname = bool(NODE_SSL_VERIFY)
        self._ssl_context.load_cert_chain(certfile=self.session.cert[0], keyfile=self.session.cert[1])
        self._logs_ws_url = f"wss://{self.address.strip('/')}:{self.port}/logs"
        self._logs_queues = []
        self._logs_bg_thread = threading.Thread(target=self._bg_fetch_logs, daemon=True)

        self._api = None
        self._started = False
        self._started_at = None

    def _prepare_config(self, config: XRayConfig):
        return _inline_tls_certificates(config)

    def make_request(self, path: str, timeout: int, **params):
        from config import NODE_CONTROL_SECRET
        headers = {}
        if NODE_CONTROL_SECRET:
            headers["X-Shahkar-Control-Secret"] = NODE_CONTROL_SECRET
        try:
            res = self.session.post(
                self._rest_api_url + path,
                timeout=timeout,
                headers=headers,
                json={"session_id": self._session_id, **params},
            )
            data = res.json()
        except Exception as e:
            exc = NodeAPIError(0, str(e))
            raise exc

        if res.status_code == 200:
            return data
        else:
            exc = NodeAPIError(res.status_code, data['detail'])
            raise exc

    @property
    def connected(self):
        if not self._session_id:
            return False
        try:
            self.make_request("/ping", timeout=3)
            return True
        except NodeAPIError:
            return False

    @property
    def started(self):
        res = self.make_request("/", timeout=3)
        return res.get('started', False)

    @property
    def api(self):
        if not self._session_id:
            raise ConnectionError("Node is not connected")

        if not self._api:
            if self._started is True:
                self._api = XRayAPI(
                    address=self.address,
                    port=self.api_port,
                    ssl_cert=self._node_cert.encode(),
                    ssl_target_name="Shahkar"
                )
            else:
                raise ConnectionError("Node is not started")

        return self._api

    def connect(self):
        self._node_cert = _pem_peer_cert(self.address, self.port, timeout=5.0)
        # Pin the node's cert (TOFU): reject a changed cert as a possible MITM.
        self.observed_cert_sha256 = verify_or_capture_pin(
            self.address, self._node_cert, self.pinned_cert_sha256
        )
        self._node_certfile = string_to_temp_file(self._node_cert)
        self.session.verify = self._node_certfile.name

        res = self.make_request("/connect", timeout=3)
        self._session_id = res['session_id']

    def disconnect(self):
        self.make_request("/disconnect", timeout=3)
        self._session_id = None

    def get_version(self):
        res = self.make_request("/", timeout=3)
        return res.get('core_version')

    def upgrade_xray(self, tag: str) -> str:
        if not self.connected:
            self.connect()
        res = self.make_request("/xray/upgrade", timeout=300, tag=tag)
        return res.get("version") or tag

    def start(self, config: XRayConfig):
        if not self.connected:
            self.connect()

        config = self._prepare_config(config)
        json_config = config.to_json()

        try:
            res = self.make_request("/start", timeout=10, config=json_config)
        except NodeAPIError as exc:
            if exc.detail == 'Xray is started already':
                return self.restart(config)
            else:
                raise exc

        self._started = True
        self._started_at = time.time()

        self._api = XRayAPI(
            address=self.address,
            port=self.api_port,
            ssl_cert=self._node_cert.encode(),
            ssl_target_name="Shahkar"
        )

        try:
            grpc.channel_ready_future(self._api._channel).result(timeout=NODE_API_READY_TIMEOUT)
        except grpc.FutureTimeoutError:
            raise ConnectionError('Failed to connect to node\'s API')

        return res

    def stop(self):
        if not self.connected:
            self.connect()

        self.make_request('/stop', timeout=5)
        self._api = None
        self._started = False
        self._started_at = None

    def hot_replace_inbounds(
        self,
        remove_tags: list,
        inbounds: list,
        *,
        timeout: int = 180,
    ) -> dict:
        """Hot-swap inbounds on the live core (Finalmask shard reload)."""
        if not self.connected:
            self.connect()
        res = self.make_request(
            "/xray/hot-replace-inbounds",
            timeout=timeout,
            remove_tags=list(remove_tags or []),
            inbounds=list(inbounds or []),
        )
        return res if isinstance(res, dict) else {"ok": True}

    def restart(self, config: XRayConfig):
        if not self.connected:
            self.connect()

        config = self._prepare_config(config)
        json_config = config.to_json()

        res = self.make_request("/restart", timeout=10, config=json_config)

        self._started = True
        self._started_at = time.time()

        self._api = XRayAPI(
            address=self.address,
            port=self.api_port,
            ssl_cert=self._node_cert.encode(),
            ssl_target_name="Shahkar"
        )

        try:
            grpc.channel_ready_future(self._api._channel).result(timeout=NODE_API_READY_TIMEOUT)
        except grpc.FutureTimeoutError:
            raise ConnectionError('Failed to connect to node\'s API')

        return res

    def _bg_fetch_logs(self):
        while self._logs_queues:
            try:
                websocket_url = f"{self._logs_ws_url}?session_id={self._session_id}&interval=0.7"
                self._ssl_context.load_verify_locations(self.session.verify)
                ws = create_connection(websocket_url, sslopt={"context": self._ssl_context}, timeout=2)
                while self._logs_queues:
                    try:
                        logs = ws.recv()
                        for buf in self._logs_queues:
                            buf.append(logs)
                    except WebSocketConnectionClosedException:
                        break
                    except WebSocketTimeoutException:
                        pass
                    except Exception:
                        pass
            except Exception:
                pass
            time.sleep(2)

    @contextmanager
    def get_logs(self):
        try:
            buf = deque(maxlen=100)
            self._logs_queues.append(buf)

            if not self._logs_bg_thread.is_alive():
                try:
                    self._logs_bg_thread.start()
                except RuntimeError:
                    self._logs_bg_thread = threading.Thread(target=self._bg_fetch_logs, daemon=True)
                    self._logs_bg_thread.start()

            yield buf

        finally:
            try:
                self._logs_queues.remove(buf)
            except ValueError:
                pass
            del buf


class _LockedRemoteRoot:
    """Proxy for an ``RPyCXRayNode``'s ``connection.root`` that funnels every
    attribute lookup *and* call through the node's ``_lock``.

    The node agent (see ``node/rpyc_service.py`` ``on_connect``) only accepts
    one active RPyC session and force-closes any previous one the moment a
    new connection arrives. With several independent background jobs (health
    check, usage recording, WireGuard/sing-box sync) each free to call
    ``node.connect()``/``node.remote`` on the *same* ``RPyCXRayNode`` at any
    time, two threads could previously decide the channel was dead at once
    and each dial a fresh connection — the node then preempted whichever
    connection the other thread was still mid-call on, surfacing as "stream
    has been closed" / "result expired" for a perfectly healthy node. Routing
    every real RPyC round trip through this proxy (which re-validates the
    connection and performs the call atomically under the same lock used by
    ``connect``/``disconnect``) makes that interleaving impossible: only one
    thread is ever actually talking to the node at a time, and a call is
    never left holding a reference to a connection another thread is about
    to tear down.
    """

    __slots__ = ("_node",)

    def __init__(self, node: "RPyCXRayNode"):
        object.__setattr__(self, "_node", node)

    # Methods that must not wait minutes behind a large WG batch sync.
    # If the node lock is held by sync, fail fast so usage/health can skip
    # this tick instead of freezing Overview (max_instances skips).
    _FAST_FAIL_METHODS = frozenset({
        "wg_transfer",
        "xray_users_transfer",
        "channel_ping",
        "wg_sync_status_json",
        "singbox_transfer",
        "fetch_xray_version",
    })
    _FAST_FAIL_TIMEOUT_SEC = 2.0

    def __getattr__(self, name):
        node = object.__getattribute__(self, "_node")
        fast = name in _LockedRemoteRoot._FAST_FAIL_METHODS

        # Do not probe attribute existence under the lock. ``hasattr(root, name)``
        # is itself an RPyC round-trip; on a stuck peer it held the lock for the
        # full sync_request_timeout and parked every usage / sing-box / sub
        # worker behind it. Missing methods raise AttributeError on the call.

        def _locked_call(*args, **kwargs):
            call_timeout = _LockedRemoteRoot._FAST_FAIL_TIMEOUT_SEC if fast else None
            if call_timeout is not None:
                got = node._lock.acquire(timeout=call_timeout)
                if not got:
                    raise TimeoutError(
                        f"node RPyC busy (skipped fast call {name})"
                    )
            else:
                # Operational calls (start/apply) still need the lock, but must
                # not wait forever behind a wedged peer — 30s is enough for a
                # healthy hand-off and short enough that orphaned threads die.
                got = node._lock.acquire(timeout=30.0)
                if not got:
                    raise TimeoutError(f"node RPyC busy (skipped call {name})")
            try:
                conn = getattr(node, "connection", None)
                if conn is None or getattr(conn, "closed", True):
                    if fast:
                        raise ConnectionError("node RPyC not connected")
                    node.connect()
                return getattr(node.connection.root, name)(*args, **kwargs)
            finally:
                if got:
                    node._lock.release()

        return _locked_call


class RPyCXRayNode:
    def __init__(self,
                 address: str,
                 port: int,
                 api_port: int,
                 ssl_key: str,
                 ssl_cert: str,
                 usage_coefficient: float = 1,
                 pinned_cert_sha256: str = None):

        class Service(rpyc.Service):
            def __init__(self,
                         on_start_funcs: List[callable] = [],
                         on_stop_funcs: List[callable] = []):
                self.on_start_funcs = on_start_funcs
                self.on_stop_funcs = on_stop_funcs

            def exposed_on_start(self):
                for func in self.on_start_funcs:
                    threading.Thread(target=func).start()

            def exposed_on_stop(self):
                for func in self.on_stop_funcs:
                    threading.Thread(target=func).start()

            def add_startup_func(self, func):
                self.on_start_funcs.append(func)

            def add_shutdown_func(self, func):
                self.on_stop_funcs.append(func)

            def on_connect(self, conn):
                pass

            def on_disconnect(self, conn):
                pass

        self.address = address
        self.port = port
        self.api_port = api_port
        self.ssl_key = ssl_key
        self.ssl_cert = ssl_cert
        self.usage_coefficient = usage_coefficient
        self.pinned_cert_sha256 = pinned_cert_sha256
        self.observed_cert_sha256 = None

        self.started = False

        self._keyfile = string_to_temp_file(ssl_key)
        self._certfile = string_to_temp_file(ssl_cert)

        self._service = Service()
        self._api = None

        # Serializes every state-changing or RPyC-round-trip operation on
        # this node (connect/disconnect/ping/remote calls — see
        # `_LockedRemoteRoot` above for why this is required, not just an
        # optimization). An RLock so a call made from *inside* an
        # already-locked section (e.g. `connect()` calling `disconnect()`)
        # doesn't deadlock the owning thread.
        self._lock = threading.RLock()
        self._next_connect_attempt = 0.0
        self._reconnect_backoff = self._RECONNECT_BACKOFF_MIN_SEC

    _CONNECT_MAX_TRIES = 3
    _CONNECT_RETRY_BASE_SEC = 0.5

    # Circuit breaker for a node that is genuinely unreachable. Without this,
    # every independent 5-30s job (usage recording, health check, WG/sing-box
    # sync) that touches this node calls `connect()` again the moment it
    # fails, each burning the full `_CONNECT_MAX_TRIES` retry loop (up to
    # ~16s) on a doomed connection — wasting a worker thread every cycle for
    # a node we already know is down. Once every attempt in `connect()` is
    # exhausted, further calls fail fast until the backoff window elapses;
    # the window doubles on each further failure (capped) and resets to the
    # minimum as soon as a connection succeeds again.
    _RECONNECT_BACKOFF_MIN_SEC = 5.0
    _RECONNECT_BACKOFF_MAX_SEC = 120.0

    def disconnect(self):
        with self._lock:
            conn = getattr(self, "connection", None)
            self.connection = None
            self.started = False
            self._api = None
            if conn is None:
                return
            try:
                if not conn.closed:
                    conn.close()
            except Exception:
                pass

    # Liveness probe timeout. Kept far below the connection's normal
    # ``sync_request_timeout`` (15s, used for real operations like config
    # apply / restart) on purpose: this method runs under ``_lock`` from both
    # ``connected`` and ``connect``, and the health-check job calls
    # ``node.connected`` for every node on every tick. A half-open TCP channel
    # (peer gone, no RST/FIN) makes an unbounded ``channel_ping`` block for the
    # full 15s while pinning ``_lock`` — serially per node, every tick — which
    # starves the 5s usage job (WireGuard ``transfer`` waits on the same lock)
    # so ``online_at``/traffic and the Overview freeze, and delays local-core
    # recovery. Bounding both round-trips keeps a dead channel from ever
    # holding the lock longer than a couple of seconds.
    _CHANNEL_VERIFY_TIMEOUT_SEC = 4.0

    def _verify_channel(self, conn, timeout: float | None = None) -> None:
        timeout = self._CHANNEL_VERIFY_TIMEOUT_SEC if timeout is None else timeout
        conn.ping(timeout=timeout)
        # ``hasattr`` on a netref and the ``channel_ping()`` call are both
        # synchronous RPyC round-trips that otherwise honour the connection's
        # 15s ``sync_request_timeout``. Temporarily shorten it so a wedged peer
        # can't hold the node lock for the full window.
        prev = conn._config.get("sync_request_timeout")
        conn._config["sync_request_timeout"] = timeout
        try:
            if hasattr(conn.root, "channel_ping"):
                conn.root.channel_ping()
        finally:
            conn._config["sync_request_timeout"] = prev

    def connect(self):
        with self._lock:
            # Another thread may have already (re)established a working
            # connection while we were waiting for the lock — reuse it
            # instead of tearing it down and forcing the node to preempt its
            # own, still-fresh session again.
            conn = getattr(self, "connection", None)
            if conn is not None and not conn.closed:
                try:
                    self._verify_channel(conn)
                    return
                except Exception:
                    pass

            now = time.time()
            if now < self._next_connect_attempt:
                raise ConnectionError(
                    f"Node {self.address} connect backoff active for "
                    f"{self._next_connect_attempt - now:.1f}s more "
                    "(node has been unreachable; not retrying every cycle)"
                )

            # Do not call disconnect() here: closing the panel-side RPyC session
            # first makes the node agent stop Xray before the replacement
            # connection arrives. Let ssl_connect preempt the stale session.
            stale_conn = getattr(self, "connection", None)
            self.connection = None
            self.started = False
            self._api = None

            last_exc = None
            for attempt in range(1, self._CONNECT_MAX_TRIES + 1):
                conn = None
                try:
                    self._node_cert = _pem_peer_cert(self.address, self.port, timeout=3.0)
                    self.observed_cert_sha256 = verify_or_capture_pin(
                        self.address, self._node_cert, self.pinned_cert_sha256
                    )
                    self._node_certfile = string_to_temp_file(self._node_cert)
                    conn = rpyc.ssl_connect(
                        self.address,
                        self.port,
                        service=self._service,
                        keyfile=self._keyfile.name,
                        certfile=self._certfile.name,
                        ca_certs=self._node_certfile.name,
                        keepalive=True,
                        config={"sync_request_timeout": 15},
                    )
                    _bound_channel_sends(conn)
                    self._verify_channel(conn)
                    self.connection = conn
                    if stale_conn is not None and stale_conn is not conn:
                        try:
                            if not stale_conn.closed:
                                stale_conn.close()
                        except Exception:
                            pass
                    self._reconnect_backoff = self._RECONNECT_BACKOFF_MIN_SEC
                    self._next_connect_attempt = 0.0
                    return
                except Exception as exc:
                    last_exc = exc
                    if conn is not None:
                        try:
                            if not conn.closed:
                                conn.close()
                        except Exception:
                            pass
                    if attempt < self._CONNECT_MAX_TRIES:
                        time.sleep(min(self._CONNECT_RETRY_BASE_SEC * attempt, 3))

            self._next_connect_attempt = time.time() + self._reconnect_backoff
            self._reconnect_backoff = min(
                self._reconnect_backoff * 2, self._RECONNECT_BACKOFF_MAX_SEC
            )
            raise last_exc or ConnectionError(f"Failed to connect to node {self.address}")

    @property
    def connected(self):
        # Never block scheduler jobs behind a long RPyC call held by another
        # thread (WG sync, health check, …). If the lock is busy, trust the
        # cached session without a ping so usage/online stats keep moving.
        acquired = self._lock.acquire(timeout=1.0)
        if not acquired:
            conn = getattr(self, "connection", None)
            return conn is not None and not getattr(conn, "closed", True)
        try:
            try:
                conn = self.connection
                if conn is None or conn.closed:
                    raise ConnectionError("not connected")
                self._verify_channel(conn)
                return True
            except Exception:
                self.disconnect()
                return False
        finally:
            self._lock.release()

    def has_live_api(self) -> bool:
        """Cheap, lock-free check for usage collectors (no RPyC ping)."""
        if not self.started or self._api is None:
            return False
        conn = getattr(self, "connection", None)
        return conn is not None and not getattr(conn, "closed", True)

    def has_live_rpyc(self) -> bool:
        """True when the control channel is already open — never dials."""
        conn = getattr(self, "connection", None)
        return conn is not None and not getattr(conn, "closed", True)

    def try_remote(self):
        """``LockedRemoteRoot`` only if already connected; never dials."""
        if not self.has_live_rpyc():
            return None
        return _LockedRemoteRoot(self)

    @property
    def remote(self):
        # Timed lock: a hung peer must not park every usage/sub thread forever
        # behind ``connect()``. Callers that only need a live channel should
        # prefer ``try_remote()``.
        acquired = self._lock.acquire(timeout=2.0)
        if not acquired:
            raise TimeoutError("node RPyC busy (remote)")
        try:
            conn = getattr(self, "connection", None)
            if conn is None or getattr(conn, "closed", True):
                self.connect()
            return _LockedRemoteRoot(self)
        finally:
            self._lock.release()

    @property
    def api(self):
        # gRPC stats client is independent of the RPyC lock; do not ping the
        # control channel here or usage recording stalls behind WG sync.
        if self._api is None:
            raise ConnectionError("Node is not connected")

        if not self.started:
            raise ConnectionError("Node is not started")

        return self._api

    def get_version(self):
        return self.remote.fetch_xray_version()

    def ensure_api(
        self, timeout: float = 5, *, refresh: bool = False, allow_unstarted: bool = False
    ) -> bool:
        """Attach the gRPC stats/API client to an already-running remote core.

        For nodes marked ``started`` out-of-band (e.g. a WireGuard relay whose
        Xray core was confirmed alive via ``get_version()`` without going
        through ``start()``/``restart()``), ``self._api`` would otherwise stay
        ``None`` forever — silently breaking per-user stats collection
        (``record_usages.py`` treats a connected+started node's ``None`` api
        as "no stats", but downstream code that blindly calls methods on it
        crashes). Best-effort: returns whether the API is usable afterwards.

        ``refresh=True`` drops a stale channel (common after Finalmask core
        blips / hot-replace) and dials again — without this, ``has_live_api``
        stays true while every ``get_users_stats`` gets Connection refused.

        ``allow_unstarted=True`` dials even though this panel process has not
        itself started the core. That is the situation right after a panel
        restart: the node's Xray is running from before, but ``started`` only
        becomes true once we decide to adopt it — and that decision needs to
        query the core first.
        """
        if self._api is not None and not refresh:
            return True
        if not self.connected or (not self.started and not allow_unstarted):
            return False
        if self._api is not None:
            try:
                self._api.close()
            except Exception:
                pass
            self._api = None
        try:
            self._api = XRayAPI(
                address=self.address,
                port=self.api_port,
                ssl_cert=self._node_cert.encode(),
                ssl_target_name="Shahkar",
            )
            grpc.channel_ready_future(self._api._channel).result(timeout=timeout)
            return True
        except Exception:
            self._api = None
            return False

    def upgrade_xray(self, tag: str) -> str:
        if not self.connected:
            self.connect()
        # Download+install of Xray-core (~30MB from GitHub) routinely exceeds the
        # default 15s RPyC sync timeout and surfaces as
        # ``EOFError: stream has been closed`` / ``result expired`` — the panel
        # then reports a failed upgrade even when the node eventually finishes.
        prev = None
        conn = getattr(self, "connection", None)
        try:
            if conn is not None:
                prev = conn._config.get("sync_request_timeout")
                conn._config["sync_request_timeout"] = max(int(prev or 15), 600)
            return self.remote.upgrade_xray(tag)
        finally:
            if conn is not None and prev is not None:
                conn._config["sync_request_timeout"] = prev

    def _prepare_config(self, config: XRayConfig):
        return _inline_tls_certificates(config)

    def start(self, config: XRayConfig):
        config = self._prepare_config(config)
        json_config = config.to_json()
        # Compress large payloads only when the node agent understands ``zlib:``
        # blobs. Shipping zlib to unpatched agents makes XRayConfig JSON-parse
        # fail (Expecting value…) and reconnect-storms the whole panel.
        payload = json_config
        if isinstance(payload, str) and len(payload) >= 200_000:
            try:
                root = self.connection.root if self.connection else None
                exposed = dir(root) if root is not None else []
                if "_decode_config_blob" in exposed or "start_from_file" in exposed:
                    import base64
                    import zlib

                    payload = "zlib:" + base64.b64encode(
                        zlib.compress(payload.encode("utf-8"), 6)
                    ).decode("ascii")
            except Exception:
                payload = json_config
        # Large WG/Finalmask configs (thousands of peers) routinely exceed the
        # default 15s RPyC sync timeout and surface as "result expired", leaving
        # the node without Xray (UDP 51820/51901 timeout for clients).
        prev = None
        prev_sock_timeout = None
        conn = getattr(self, "connection", None)
        sock = None
        try:
            if conn is not None:
                prev = conn._config.get("sync_request_timeout")
                conn._config["sync_request_timeout"] = max(int(prev or 15), 600)
                # Iran↔abroad paths also hit SSL *write* timeouts while streaming
                # multi-MB configs; bump the underlying socket so send() can finish.
                try:
                    sock = conn._channel.stream.sock
                    prev_sock_timeout = sock.gettimeout()
                    sock.settimeout(max(float(prev_sock_timeout or 0), 600.0))
                except Exception:
                    sock = None
            self.remote.start(payload)
        finally:
            if conn is not None and prev is not None:
                conn._config["sync_request_timeout"] = prev
            if sock is not None and prev_sock_timeout is not None:
                try:
                    sock.settimeout(prev_sock_timeout)
                except Exception:
                    pass
        self.started = True

        # connect to API
        self._api = XRayAPI(
            address=self.address,
            port=self.api_port,
            ssl_cert=self._node_cert.encode(),
            ssl_target_name="Shahkar"
        )
        try:
            grpc.channel_ready_future(self._api._channel).result(timeout=NODE_API_READY_TIMEOUT)
        except grpc.FutureTimeoutError:

            start_time = time.time()
            end_time = start_time + 3  # check logs for 3 seconds
            last_log = ''
            with self.get_logs() as logs:
                while time.time() < end_time:
                    if logs:
                        last_log = logs[-1].strip().split('\n')[-1]
                    time.sleep(0.1)

            self._api = None

            if re.search(r'[Ff]ailed', last_log):
                raise RuntimeError(last_log)

            # An unreachable stats API is not the same thing as a dead core. If
            # the core answers over RPyC it is serving users right now, and
            # raising here would make the caller tear it back down to native
            # WireGuard and restart it on the next tick — dropping every live
            # session to fix nothing. Leave ``_api`` unset; ``ensure_api``
            # re-attaches it on a later pass.
            try:
                version = self.remote.fetch_xray_version()
            except Exception:
                version = None
            if version:
                return

            raise ConnectionError('Failed to connect to node\'s API')

    def stop(self):
        self.remote.stop()
        self.started = False
        self._api = None

    def hot_replace_inbounds(
        self,
        remove_tags: list,
        inbounds: list,
        *,
        timeout: int = 180,
    ) -> dict:
        """Hot-swap inbounds on the live core (Finalmask shard reload).

        Calls the node agent's ``xray_hot_replace_inbounds_json`` which runs
        ``xray api rmi/adi`` locally. Older agents without that method raise
        AttributeError so the caller can fall back to a full restart.
        """
        import json

        remote = self.remote
        # RPyC netrefs make bare ``hasattr`` unreliable (often True for any
        # name, then the real call burns the full sync_request_timeout).
        # ``dir(root)`` lists actually-exposed methods.
        try:
            root = self.connection.root if self.connection else None
            exposed = dir(root) if root is not None else []
            has_rpc = "xray_hot_replace_inbounds_json" in exposed
        except Exception:
            has_rpc = False
        if not has_rpc:
            raise AttributeError("node agent has no xray_hot_replace_inbounds_json")
        payload = json.dumps(
            {
                "remove_tags": list(remove_tags or []),
                "inbounds": list(inbounds or []),
                "timeout": int(timeout),
            },
            separators=(",", ":"),
        )
        prev = None
        conn = getattr(self, "connection", None)
        try:
            if conn is not None:
                prev = conn._config.get("sync_request_timeout")
                # Large Finalmask shards need well above the default 15s RPyC
                # budget or the call surfaces as "result expired".
                conn._config["sync_request_timeout"] = max(int(prev or 15), int(timeout))
            raw = remote.xray_hot_replace_inbounds_json(payload)
        finally:
            if conn is not None and prev is not None:
                conn._config["sync_request_timeout"] = prev
        if isinstance(raw, str):
            try:
                return json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return {"ok": False, "detail": raw}
        return raw if isinstance(raw, dict) else {"ok": bool(raw)}

    def restart(self, config: XRayConfig):
        """Restart remote Xray — use stop+start so older node agents with a
        broken ``restart()`` (missing ``connection.peer``) still recover."""
        try:
            self.stop()
        except Exception:
            self.started = False
            self._api = None
        self.start(config)

    @contextmanager
    def get_logs(self):
        if not self.connected:
            raise ConnectionError("Node is not connected")

        try:
            self.__curr_logs
        except AttributeError:
            self.__curr_logs = 0

        try:
            buf = deque(maxlen=100)

            if self.__curr_logs <= 0:
                self.__curr_logs = 1
                self.__bgsrv = rpyc.BgServingThread(self.connection)
            else:
                if not self.__bgsrv._active:
                    self.__bgsrv = rpyc.BgServingThread(self.connection)
                self.__curr_logs += 1

            logs = self.remote.fetch_logs(buf.append)
            yield buf

        finally:
            if self.__curr_logs <= 1:
                self.__curr_logs = 0
                self.__bgsrv.stop()
            else:
                if not self.__bgsrv._active:
                    self.__bgsrv = rpyc.BgServingThread(self.connection)
                self.__curr_logs -= 1

            if logs:
                logs.stop()

    def on_start(self, func: callable):
        self._service.add_startup_func(func)
        return func

    def on_stop(self, func: callable):
        self._service.add_shutdown_func(func)
        return func


class XRayNode:
    def __new__(self,
                address: str,
                port: int,
                api_port: int,
                ssl_key: str,
                ssl_cert: str,
                usage_coefficient: float = 1,
                pinned_cert_sha256: str = None):

        # trying to detect what's the server of node
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            s.connect((address, port))
            s.send(b'HEAD / HTTP/1.0\r\n\r\n')
            data = s.recv(1024)
            s.close()
            # An RPyC agent behind TLS answers plaintext with a TLS alert (or
            # nothing) — only a real HTTP banner means the REST (uvicorn) agent.
            # Matters when the node is reached through a local SSH forward,
            # where connect()/recv() succeed even though the far end is RPyC.
            if not data.startswith(b'HTTP'):
                raise ValueError("not an HTTP node agent")
            # it might be uvicorn
            return ReSTXRayNode(
                address=address,
                port=port,
                api_port=api_port,
                ssl_key=ssl_key,
                ssl_cert=ssl_cert,
                usage_coefficient=usage_coefficient,
                pinned_cert_sha256=pinned_cert_sha256
            )
        except Exception:
            # if might be rpyc
            return RPyCXRayNode(
                address=address,
                port=port,
                api_port=api_port,
                ssl_key=ssl_key,
                ssl_cert=ssl_cert,
                usage_coefficient=usage_coefficient,
                pinned_cert_sha256=pinned_cert_sha256
            )
