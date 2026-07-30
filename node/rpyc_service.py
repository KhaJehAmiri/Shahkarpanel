import time
from socket import socket
from threading import Thread

import rpyc

from config import XRAY_ASSETS_PATH, XRAY_EXECUTABLE_PATH
from logger import logger
from singbox import SingBoxManager, SingBoxSpec
from speed_limit import SpeedLimitManager, peer_limits_from_spec
from wireguard import WireGuardManager, WireGuardSpec
from wg_autoscale import InterfaceSpec, WireGuardAutoScale
from xray import XRayConfig, XRayCore


class XrayCoreLogsHandler(object):
    def __init__(self, core: XRayCore, callback: callable, interval: float = 0.6):
        self.core = core
        self.callback = callback
        self.interval = interval
        self.active = True
        self.thread = Thread(target=self.cast)
        self.thread.start()

    def stop(self):
        self.active = False
        self.thread.join()

    def cast(self):
        with self.core.get_logs() as logs:
            cache = ''
            last_sent_ts = 0
            while self.active:
                if time.time() - last_sent_ts >= self.interval and cache:
                    self.callback(cache)
                    cache = ''
                    last_sent_ts = time.time()

                if not logs:
                    time.sleep(0.2)
                    continue

                log = logs.popleft()
                cache += f'{log}\n'


@rpyc.service
class XrayService(rpyc.Service):
    def __init__(self):
        self.core = None
        self.connection = None
        self.wg = WireGuardManager()
        self.wg_autoscale = WireGuardAutoScale()
        self.singbox = SingBoxManager()
        self.speed_limit = SpeedLimitManager()

    def _close_stale_connection(self, conn, *, new_peer: str) -> None:
        """Drop a superseded panel session without tearing down the active one."""
        old_peer = getattr(conn, "peer", "?")
        if old_peer == new_peer:
            logger.warning(
                f"New connection from {new_peer} replaced stale panel session")
        else:
            logger.warning(
                f"New connection from {new_peer} took over from {old_peer}")
        try:
            if not conn.closed:
                conn.close()
        except Exception:
            pass

    def on_connect(self, conn):
        peer, _ = socket.getpeername(conn._channel.stream.sock)
        conn.peer = peer

        old = self.connection
        self.connection = conn
        if old is not None and old is not conn:
            self._close_stale_connection(old, new_peer=peer)

        logger.warning(f"Connected to {peer}")

    def on_disconnect(self, conn):
        if conn is not self.connection:
            return

        logger.warning(f"Disconnected from {getattr(conn, 'peer', '?')}")

        # Keep Xray running across transient panel reconnects so client
        # traffic is not dropped when the control channel drops. Explicit
        # stop()/restart() still manage the core lifecycle.
        self.connection = None

    def _panel_peer_ip(self) -> str:
        conn = self.connection
        if conn is not None and getattr(conn, "peer", None):
            return conn.peer
        return "127.0.0.1"

    @rpyc.exposed
    def start(self, config: str):
        from xray import _kill_stale_stdin_xray, find_stdin_xray_pids

        config_obj = XRayConfig(config, self._panel_peer_ip())
        if self.core is not None:
            proc = getattr(self.core, "process", None)
            if proc is not None and proc.poll() is None:
                self.core.restart(config_obj)
                return
            self.stop()
        elif find_stdin_xray_pids(XRAY_EXECUTABLE_PATH):
            # Out-of-band starts (manual recovery, crashed panel session) must
            # not stack a second stdin Xray on the same UDP/TCP ports.
            _kill_stale_stdin_xray(XRAY_EXECUTABLE_PATH)

        try:
            self.core = XRayCore(executable_path=XRAY_EXECUTABLE_PATH,
                                 assets_path=XRAY_ASSETS_PATH)

            if self.connection and hasattr(self.connection.root, 'on_start'):
                @self.core.on_start
                def on_start():
                    try:
                        if self.connection:
                            self.connection.root.on_start()
                    except Exception as exc:
                        logger.debug('Peer on_start exception:', exc)
            else:
                logger.debug(
                    "Peer doesn't have on_start function on it's service, skipped")

            if self.connection and hasattr(self.connection.root, 'on_stop'):
                @self.core.on_stop
                def on_stop():
                    try:
                        if self.connection:
                            self.connection.root.on_stop()
                    except Exception as exc:
                        logger.debug('Peer on_stop exception:', exc)
            else:
                logger.debug(
                    "Peer doesn't have on_stop function on it's service, skipped")

            self.core.start(config_obj)
        except Exception as exc:
            logger.error(exc)
            raise exc

    @rpyc.exposed
    def stop(self):
        if self.core:
            try:
                self.core.stop()
            except RuntimeError:
                pass
        self.core = None

    @rpyc.exposed
    def restart(self, config: str):
        if self.core is None:
            return self.start(config)
        config = XRayConfig(config, self._panel_peer_ip())
        self.core.restart(config)

    @rpyc.exposed
    def xray_hot_replace_inbounds_json(self, payload_json: str) -> str:
        """Hot-swap inbounds on the live core (Finalmask shard reload).

        ``payload_json``: ``{"remove_tags": [...], "inbounds": [...]}``. Runs
        ``xray api rmi/adi`` against the loopback plaintext API so only the
        touched shard blips — no full core restart, tunnel stays up.
        """
        import json

        from xray import hot_replace_inbounds

        if self.core is None or not self.core.started:
            return json.dumps({"ok": False, "detail": "xray core is not running"})
        data = json.loads(payload_json or "{}")
        result = hot_replace_inbounds(
            XRAY_EXECUTABLE_PATH,
            list(data.get("remove_tags") or []),
            list(data.get("inbounds") or []),
            # Large Finalmask shards routinely exceed the old 30s CLI budget.
            timeout=float(data.get("timeout") or 180.0),
        )
        return json.dumps(result)

    @rpyc.exposed
    def wg_apply(self, spec):
        import json

        from rpyc.utils.classic import obtain

        if isinstance(spec, str):
            plain = json.loads(spec)
        else:
            # Legacy callers may still pass a netref dict — obtain locally first.
            plain = obtain(spec)
        wg_spec = WireGuardSpec.from_dict(plain)
        self.wg.apply_specs([wg_spec])
        limits = peer_limits_from_spec(plain)
        if limits:
            self.speed_limit.apply_wireguard(wg_spec.interface, limits)

    @rpyc.exposed
    def wg_apply_json(self, spec_json: str):
        import json

        plain = json.loads(spec_json)
        wg_spec = WireGuardSpec.from_dict(plain)
        self.wg.apply_specs([wg_spec])
        limits = peer_limits_from_spec(plain)
        if limits:
            self.speed_limit.apply_wireguard(wg_spec.interface, limits)

    @rpyc.exposed
    def wg_apply_specs_json(self, specs_json: str):
        import json

        raw = json.loads(specs_json)
        specs = [WireGuardSpec.from_dict(item) for item in raw]
        self.wg.apply_specs(specs)
        for plain, wg_spec in zip(raw, specs):
            limits = peer_limits_from_spec(plain)
            if limits:
                self.speed_limit.apply_wireguard(wg_spec.interface, limits)

    @rpyc.exposed
    def wg_open_udp_ports(self, ports) -> int:
        """Open UDP INPUT ports on the host (plain/AWG/Xray-native WG)."""
        from rpyc.utils.classic import obtain

        plain = obtain(ports) if ports is not None else []
        if isinstance(plain, str):
            import json

            plain = json.loads(plain)
        wanted = [int(p) for p in (plain or []) if p]
        self.wg.open_udp_ports(wanted)
        return len(wanted)

    @rpyc.exposed
    def wg_apply_batch_json(self, payload_json: str) -> str:
        """Resumable incremental peer apply (panel high-scale sync)."""
        import json

        data = json.loads(payload_json or "{}")
        result = self.wg.apply_batch(
            str(data.get("interface") or ""),
            generation=int(data.get("generation") or 0),
            cursor=int(data.get("cursor") or 0),
            peers=list(data.get("peers") or []),
            removes=list(data.get("removes") or []),
        )
        return json.dumps(result)

    @rpyc.exposed
    def wg_sync_status_json(self, interface: str = "") -> str:
        import json

        iface = (interface or "").strip() or None
        return json.dumps(self.wg.sync_status(iface))

    @rpyc.exposed
    def wg_transfer(self, interface: str) -> str:
        import json
        return json.dumps(self.wg.get_transfer(interface))

    @rpyc.exposed
    def wg_down(self, interface: str):
        self.wg.teardown(interface)

    @rpyc.exposed
    def wg_warp_tproxy(self, payload_json: str) -> str:
        """Divert kernel WG clients into Xray dokodemo for WARP egress."""
        import json

        payload = json.loads(payload_json or "{}")
        ok = self.wg.apply_warp_tproxy(
            enabled=bool(payload.get("enabled")),
            subnets=[str(s) for s in (payload.get("subnets") or [])],
            port=int(payload.get("port") or 0),
            interfaces=[str(i) for i in (payload.get("interfaces") or [])],
        )
        return json.dumps({"ok": bool(ok)})

    @rpyc.exposed
    def wg_amnezia_available(self) -> bool:
        return self.wg.amnezia_available()

    @rpyc.exposed
    def wg_recover_awg_interface(self, interface: str) -> bool:
        return self.wg.recover_awg_interface(interface)

    @rpyc.exposed
    def wg_reconcile_awg_endpoints(self, interface: str, stale_sec: int = 180) -> int:
        return self.wg.reconcile_awg_endpoints(interface, stale_sec=int(stale_sec))

    @rpyc.exposed
    def wg_flush_bad_endpoints(self, interface: str) -> int:
        return self.wg.flush_bad_endpoints(interface)

    @rpyc.exposed
    def wg_prepare_peer_for_connect(self, interface: str, public_key: str) -> bool:
        return self.wg.prepare_peer_for_connect(interface, public_key)

    @rpyc.exposed
    def wg_flush_stale_peers(
        self, interface: str, max_age_sec: int = 35, idle_sec: int = 5, traffic_only: bool = True
    ) -> int:
        return self.wg.flush_stale_peers(
            interface,
            max_age_sec=int(max_age_sec),
            idle_sec=int(idle_sec),
            traffic_only=bool(traffic_only),
        )

    @rpyc.exposed
    def wg_autoscale_create_interface_json(self, spec_json: str):
        import json

        self.wg_autoscale.create_interface(InterfaceSpec.from_dict(json.loads(spec_json)))

    @rpyc.exposed
    def wg_autoscale_hot_add_peer(
        self, interface: str, public_key: str, allowed_ips: str, preshared_key: str = ""
    ):
        self.wg_autoscale.hot_add_peer(
            interface,
            public_key,
            allowed_ips,
            preshared_key=preshared_key or None,
        )

    @rpyc.exposed
    def wg_autoscale_toggle_peer(
        self, interface: str, public_key: str, active: bool, allowed_ips: str, preshared_key: str = ""
    ):
        self.wg_autoscale.toggle_peer(
            interface,
            public_key,
            active=bool(active),
            allowed_ips=allowed_ips,
            preshared_key=preshared_key or None,
        )

    @rpyc.exposed
    def wg_autoscale_show_dump_json(self) -> str:
        import json

        return json.dumps(self.wg_autoscale.show_dump_all())

    @rpyc.exposed
    def wg_autoscale_transfer_json(self, interface: str) -> str:
        import json

        return json.dumps(self.wg_autoscale.get_transfer(interface))

    @rpyc.exposed
    def singbox_apply_json(self, spec_json: str):
        import json
        self.singbox.apply(SingBoxSpec.from_dict(json.loads(spec_json)))

    @rpyc.exposed
    def singbox_transfer(self) -> str:
        import json
        return json.dumps(self.singbox.get_transfer())

    @rpyc.exposed
    def xray_users_transfer(self, reset: bool = True) -> str:
        """Per-user Finalmask/Xray interval bytes via loopback StatsService.

        Panel gRPC to the public TLS API port flaps during hot-replace; reading
        ``127.0.0.1:<api+1>`` over RPyC stays reliable while the control
        session is up. Shape matches ``singbox_transfer`` / ``wg_transfer``.
        """
        import json

        from config import XRAY_API_PORT
        from v2ray_stats import query_user_transfer

        local_port = int(XRAY_API_PORT) + 1
        try:
            out = query_user_transfer(
                "127.0.0.1", local_port, reset=bool(reset), timeout=8.0
            )
        except Exception:
            out = {}
        return json.dumps(out or {})

    @rpyc.exposed
    def singbox_available(self) -> bool:
        return self.singbox.available()

    @rpyc.exposed
    def singbox_down(self):
        self.singbox.stop()

    @rpyc.exposed
    def singbox_tls_status(self, certificate_path: str = "/var/lib/shahkar-node/tls/cert.pem") -> str:
        import json
        from tls_inspect import inspect_cert_file

        return json.dumps(inspect_cert_file(certificate_path))

    @rpyc.exposed
    def channel_ping(self) -> bool:
        """Cheap liveness probe for the panel control channel."""
        return True

    @rpyc.exposed
    def fetch_xray_version(self):
        if self.core is None or not self.core.started:
            raise ProcessLookupError("Xray has not been started")

        return self.core.version

    @rpyc.exposed
    def upgrade_xray(self, tag: str) -> str:
        """Download and install Xray release tag. Panel should restart the node after."""
        from xray_upgrade import install_xray_release

        if self.core is not None and self.core.started:
            try:
                self.core.stop()
            except Exception:
                pass

        version = install_xray_release(tag)
        self.core = XRayCore(
            executable_path=XRAY_EXECUTABLE_PATH,
            assets_path=XRAY_ASSETS_PATH,
        )
        return version

    @rpyc.exposed
    def fetch_logs(self, callback: callable) -> XrayCoreLogsHandler:
        if self.core:
            logs = XrayCoreLogsHandler(self.core, callback)
            logs.exposed_stop = logs.stop
            logs.exposed_cast = logs.cast
            return logs
