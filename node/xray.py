import atexit
import json
import os
import re
import signal
import subprocess
import threading
import time
from collections import deque
from contextlib import contextmanager

from config import DEBUG, SSL_CERT_FILE, SSL_KEY_FILE, XRAY_API_HOST, XRAY_API_PORT, INBOUNDS
from logger import logger

_XRAY_STOP_TIMEOUT = 5.0


def _stdin_xray_cmd_prefix(executable_path: str) -> list[str]:
    return [executable_path, "run", "-config", "stdin:"]


def _find_stdin_xray_pids_via_proc(executable_path: str) -> list[int]:
    prefix = _stdin_xray_cmd_prefix(executable_path)
    pids: list[int] = []
    try:
        proc_entries = os.listdir("/proc")
    except OSError:
        return pids
    for entry in proc_entries:
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/cmdline", "rb") as fh:
                raw = fh.read()
        except OSError:
            continue
        if not raw:
            continue
        argv = raw.split(b"\0")
        if argv and argv[-1] == b"":
            argv.pop()
        decoded = [part.decode(errors="replace") for part in argv[: len(prefix)]]
        if decoded == prefix:
            pids.append(int(entry))
    return pids


def find_stdin_xray_pids(executable_path: str) -> list[int]:
    """Return PIDs of ``<executable_path> run -config stdin:`` processes."""
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", f"^{re.escape(executable_path)} run -config stdin:"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return []
    except FileNotFoundError:
        return _find_stdin_xray_pids_via_proc(executable_path)
    pids: list[int] = []
    for line in out.strip().splitlines():
        if line.strip().isdigit():
            pids.append(int(line.strip()))
    return pids


def _terminate_pids(pids: list[int], *, wait_sec: float = 5.0) -> None:
    if not pids:
        return
    alive = list(dict.fromkeys(pids))
    for pid in alive:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + wait_sec
    while time.monotonic() < deadline:
        still = []
        for pid in alive:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                continue
            still.append(pid)
        if not still:
            return
        time.sleep(0.1)
        alive = still
    for pid in alive:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    time.sleep(0.2)


def _kill_stale_stdin_xray(executable_path: str, keep_pid: int | None = None) -> None:
    """Ensure no orphan ``xray run -config stdin`` survives a restart."""
    pids = find_stdin_xray_pids(executable_path)
    targets = [pid for pid in pids if not (keep_pid and pid == keep_pid)]
    _terminate_pids(targets)


class XRayConfig(dict):
    """
    Loads Xray config json
    config must contain an inbound with the API_INBOUND tag name which handles API requests
    """

    def __init__(self, config: str, peer_ip: str):
        config = json.loads(config)

        self.api_host = XRAY_API_HOST
        self.api_port = XRAY_API_PORT
        # Plaintext, loopback-only HandlerService mirror of the (TLS) panel API.
        # Lets the local agent run ``xray api adi/rmi`` to hot-swap a single
        # Finalmask shard inbound without a full core restart (the Reality
        # tunnel + other inbounds stay up). Never exposed off 127.0.0.1.
        self.local_api_host = "127.0.0.1"
        self.local_api_port = int(XRAY_API_PORT) + 1
        self.ssl_cert = SSL_CERT_FILE
        self.ssl_key = SSL_KEY_FILE
        self.peer_ip = peer_ip

        super().__init__(config)
        self._apply_api()

    def to_json(self, **json_kwargs):
        return json.dumps(self, **json_kwargs)

    def _apply_api(self):
        for inbound in self.get('inbounds', []).copy():
            if inbound.get('protocol') == 'dokodemo-door' and inbound.get('tag') in (
                'API_INBOUND', 'API_LOCAL_INBOUND'
            ):
                self['inbounds'].remove(inbound)

            elif INBOUNDS and inbound.get('tag') not in INBOUNDS:
                self['inbounds'].remove(inbound)

        for rule in self.get('routing', {}).get("rules", []):
            api_tag = self.get('api', {}).get('tag')
            if api_tag and rule.get('outboundTag') == api_tag:
                self['routing']['rules'].remove(rule)

        self["api"] = {
            "services": [
                "HandlerService",
                "StatsService",
                "LoggerService"
            ],
            "tag": "API"
        }
        self["stats"] = {}
        inbound = {
            "listen": self.api_host,
            "port": self.api_port,
            "protocol": "dokodemo-door",
            "settings": {
                "address": "127.0.0.1"
            },
            "streamSettings": {
                "security": "tls",
                "tlsSettings": {
                    "certificates": [
                        {
                            "certificateFile": self.ssl_cert,
                            "keyFile": self.ssl_key
                        }
                    ]
                }
            },
            "tag": "API_INBOUND"
        }
        try:
            self["inbounds"].insert(0, inbound)
        except KeyError:
            self["inbounds"] = []
            self["inbounds"].insert(0, inbound)

        # Loopback plaintext mirror for the local ``xray api`` CLI (the TLS
        # inbound above cannot be dialed by the CLI, which speaks plain gRPC).
        local_inbound = {
            "listen": self.local_api_host,
            "port": self.local_api_port,
            "protocol": "dokodemo-door",
            "settings": {
                "address": "127.0.0.1"
            },
            "tag": "API_LOCAL_INBOUND"
        }
        self["inbounds"].insert(1, local_inbound)

        rule = {
            "inboundTag": [
                "API_INBOUND"
            ],
            "source": [
                "127.0.0.1",
                self.peer_ip
            ],
            "outboundTag": "API",
            "type": "field"
        }
        local_rule = {
            "inboundTag": [
                "API_LOCAL_INBOUND"
            ],
            "source": [
                "127.0.0.1"
            ],
            "outboundTag": "API",
            "type": "field"
        }
        try:
            self["routing"]["rules"].insert(0, rule)
        except KeyError:
            self["routing"] = {"rules": []}
            self["routing"]["rules"].insert(0, rule)
        self["routing"]["rules"].insert(1, local_rule)


class XRayCore:
    def __init__(self,
                 executable_path: str = "/usr/bin/xray",
                 assets_path: str = "/usr/share/xray"):
        self.executable_path = executable_path
        self.assets_path = assets_path

        self.version = self.get_version()
        self.process = None
        self.restarting = False

        self._logs_buffer = deque(maxlen=100)
        self._temp_log_buffers = {}
        self._on_start_funcs = []
        self._on_stop_funcs = []
        self._env = {
            "XRAY_LOCATION_ASSET": assets_path
        }

        atexit.register(lambda: self.stop() if self.started else None)

    def get_version(self):
        cmd = [self.executable_path, "version"]
        output = subprocess.check_output(
            cmd, stderr=subprocess.STDOUT).decode('utf-8')
        m = re.match(r'^Xray (\d+\.\d+\.\d+)', output)
        if m:
            return m.groups()[0]

    def __capture_process_logs(self):
        def capture_and_debug_log():
            while self.process:
                output = self.process.stdout.readline()
                if output:
                    output = output.strip()
                    self._logs_buffer.append(output)
                    for buf in list(self._temp_log_buffers.values()):
                        buf.append(output)
                    logger.debug(output)

                elif not self.process or self.process.poll() is not None:
                    break

        def capture_only():
            while self.process:
                output = self.process.stdout.readline()
                if output:
                    output = output.strip()
                    self._logs_buffer.append(output)
                    for buf in list(self._temp_log_buffers.values()):
                        buf.append(output)

                elif not self.process or self.process.poll() is not None:
                    break

        if DEBUG:
            threading.Thread(target=capture_and_debug_log).start()
        else:
            threading.Thread(target=capture_only).start()

    @contextmanager
    def get_logs(self):
        buf = deque(self._logs_buffer, maxlen=100)
        buf_id = id(buf)
        try:
            self._temp_log_buffers[buf_id] = buf
            yield buf
        except (EOFError, TimeoutError):
            pass
        finally:
            del self._temp_log_buffers[buf_id]
            del buf

    @property
    def started(self):
        if not self.process:
            return False

        if self.process.poll() is None:
            return True

        return False

    def start(self, config: XRayConfig):
        if self.started is True:
            raise RuntimeError("Xray is started already")

        keep_pid = self.process.pid if self.process and self.process.poll() is None else None
        _kill_stale_stdin_xray(self.executable_path, keep_pid=keep_pid)

        if config.get('log', {}).get('logLevel') in ('none', 'error'):
            config['log']['logLevel'] = 'warning'

        cmd = [
            self.executable_path,
            "run",
            '-config',
            'stdin:'
        ]
        self.process = subprocess.Popen(
            cmd,
            env=self._env,
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            universal_newlines=True
        )
        self.process.stdin.write(config.to_json())
        self.process.stdin.flush()
        self.process.stdin.close()

        self.__capture_process_logs()

        # execute on start functions
        for func in self._on_start_funcs:
            threading.Thread(target=func).start()

    def stop(self):
        proc = self.process
        if not proc:
            return

        try:
            proc.terminate()
            proc.wait(timeout=_XRAY_STOP_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        self.process = None
        logger.warning("Xray core stopped")

        # execute on stop functions
        for func in self._on_stop_funcs:
            threading.Thread(target=func).start()

    def restart(self, config: XRayConfig):
        if self.restarting is True:
            return

        self.restarting = True
        try:
            logger.warning("Restarting Xray core...")
            self.stop()
            _kill_stale_stdin_xray(self.executable_path)
            self.start(config)
        finally:
            self.restarting = False

    def on_start(self, func: callable):
        self._on_start_funcs.append(func)
        return func

    def on_stop(self, func: callable):
        self._on_stop_funcs.append(func)
        return func


def local_api_server() -> str:
    """Address of the loopback plaintext HandlerService (see XRayConfig)."""
    return f"127.0.0.1:{int(XRAY_API_PORT) + 1}"


def hot_replace_inbounds(
    executable_path: str,
    remove_tags: list,
    inbounds: list,
    *,
    timeout: float = 30.0,
) -> dict:
    """Swap inbounds on the *live* core via the local ``xray api`` CLI.

    ``xray api rmi``/``adi`` build the full typed config from JSON inside the
    CLI, which is the only way to hot-add a WireGuard+Finalmask inbound — the
    gRPC HandlerService needs a serialized ``core.InboundHandlerConfig`` that
    no Python client can produce for custom stream transports. Routing rules
    referencing a re-added tag survive in the running core, so a swapped shard
    keeps its outbound (tunnel/WARP) without touching routing.

    Used by the Finalmask shard reload: only the changed shard's clients blip
    for the rmi→adi moment; the Reality tunnel and every other inbound stay up.
    """
    import tempfile

    server = local_api_server()
    removed, remove_errors = [], {}
    for tag in remove_tags or []:
        try:
            proc = subprocess.run(
                [executable_path, "api", "rmi", f"--server={server}", str(tag)],
                capture_output=True, text=True, timeout=timeout,
            )
            if proc.returncode == 0:
                removed.append(tag)
            else:
                # Unknown tag is fine (first add of a shard); record others.
                remove_errors[tag] = (proc.stderr or proc.stdout or "").strip()
        except Exception as exc:  # noqa: BLE001 - reported to the panel
            remove_errors[tag] = str(exc)

    if not inbounds:
        return {"ok": True, "removed": removed, "remove_errors": remove_errors}

    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", prefix="finalmask-shard-", delete=False
    ) as fh:
        json.dump({"inbounds": list(inbounds)}, fh)
        conf_path = fh.name
    try:
        proc = subprocess.run(
            [executable_path, "api", "adi", f"--server={server}", conf_path],
            capture_output=True, text=True, timeout=timeout,
        )
        ok = proc.returncode == 0
        detail = (proc.stderr or proc.stdout or "").strip()
    except Exception as exc:  # noqa: BLE001 - reported to the panel
        ok, detail = False, str(exc)
    finally:
        try:
            os.unlink(conf_path)
        except OSError:
            pass

    if not ok:
        logger.warning("Finalmask hot add failed: %s", detail)
    return {
        "ok": ok,
        "removed": removed,
        "remove_errors": remove_errors,
        "detail": detail if not ok else "",
    }
