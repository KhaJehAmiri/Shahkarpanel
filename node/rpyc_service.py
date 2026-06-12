import time
from socket import socket
from threading import Thread

import rpyc

from config import XRAY_ASSETS_PATH, XRAY_EXECUTABLE_PATH
from logger import logger
from singbox import SingBoxManager, SingBoxSpec
from wireguard import WireGuardManager, WireGuardSpec
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
        self.singbox = SingBoxManager()

    def on_connect(self, conn):
        if self.connection:
            try:
                self.connection.ping()
                if self.connection.peer is not None:
                    logger.warning(
                        f'New connection rejected, already connected to {self.connection.peer}')
                return conn.close()
            except (EOFError, TimeoutError, AttributeError):
                if hasattr(self.connection, "peer"):
                    logger.warning(
                        f'Previous connection from {self.connection.peer} has lost')

        peer, _ = socket.getpeername(conn._channel.stream.sock)
        self.connection = conn
        self.connection.peer = peer
        logger.warning(f'Connected to {self.connection.peer}')

    def on_disconnect(self, conn):
        if conn is self.connection:
            logger.warning(f'Disconnected from {self.connection.peer}')

            if self.core is not None:
                self.core.stop()

            self.core = None
            self.connection = None

    def _panel_peer_ip(self) -> str:
        conn = self.connection
        if conn is not None and getattr(conn, "peer", None):
            return conn.peer
        return "127.0.0.1"

    @rpyc.exposed
    def start(self, config: str):
        if self.core is not None:
            self.stop()

        try:
            config = XRayConfig(config, self._panel_peer_ip())
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

            self.core.start(config)
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
    def wg_apply(self, spec):
        import json

        from rpyc.utils.classic import obtain

        if isinstance(spec, str):
            plain = json.loads(spec)
        else:
            # Legacy callers may still pass a netref dict — obtain locally first.
            plain = obtain(spec)
        self.wg.apply(WireGuardSpec.from_dict(plain))

    @rpyc.exposed
    def wg_apply_json(self, spec_json: str):
        import json

        self.wg.apply(WireGuardSpec.from_dict(json.loads(spec_json)))

    @rpyc.exposed
    def wg_apply_specs_json(self, specs_json: str):
        import json

        specs = [WireGuardSpec.from_dict(item) for item in json.loads(specs_json)]
        self.wg.apply_specs(specs)

    @rpyc.exposed
    def wg_transfer(self, interface: str) -> str:
        import json
        return json.dumps(self.wg.get_transfer(interface))

    @rpyc.exposed
    def wg_down(self, interface: str):
        self.wg.teardown(interface)

    @rpyc.exposed
    def wg_amnezia_available(self) -> bool:
        return self.wg.amnezia_available()

    @rpyc.exposed
    def singbox_apply_json(self, spec_json: str):
        import json
        self.singbox.apply(SingBoxSpec.from_dict(json.loads(spec_json)))

    @rpyc.exposed
    def singbox_transfer(self) -> str:
        import json
        return json.dumps(self.singbox.get_transfer())

    @rpyc.exposed
    def singbox_available(self) -> bool:
        return self.singbox.available()

    @rpyc.exposed
    def singbox_down(self):
        self.singbox.stop()

    @rpyc.exposed
    def singbox_tls_status(self, certificate_path: str = "/var/lib/nexuspanel-node/tls/cert.pem") -> str:
        import json
        from tls_inspect import inspect_cert_file

        return json.dumps(inspect_cert_file(certificate_path))

    @rpyc.exposed
    def fetch_xray_version(self):
        if self.core is None:
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
