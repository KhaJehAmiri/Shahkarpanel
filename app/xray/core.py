import atexit
import os
import re
import signal
import subprocess
import threading
import time
from collections import deque
from contextlib import contextmanager

from app import logger
from app.xray.config import XRayConfig
from config import (
    DEBUG,
    XRAY_RESTART_PORT_RECLAIM_TIMEOUT,
    XRAY_RESTART_STOP_TIMEOUT,
)

_lifecycle_lock = threading.RLock()
_HEALTH_RESTART_COOLDOWN_SEC = 20.0


def _stdin_xray_cmd_prefix(executable_path: str) -> list[str]:
    return [executable_path, "run", "-config", "stdin:"]


def _find_stdin_xray_pids_via_proc(executable_path: str) -> list[int]:
    """``/proc``-only fallback for :func:`find_stdin_xray_pids`.

    Used when ``pgrep`` isn't installed (e.g. the ``procps`` package is
    missing from the panel image) so the caller never mistakes "the tool to
    check is missing" for "no Xray process is running".
    """
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
        decoded = [part.decode(errors="replace") for part in argv[:len(prefix)]]
        if decoded == prefix:
            pids.append(int(entry))
    return pids


def find_stdin_xray_pids(executable_path: str) -> list[int]:
    """Return PIDs of ``<executable_path> run -config stdin:`` processes.

    Prefers ``pgrep`` (fast, well-tested pattern matching) and transparently
    falls back to scanning ``/proc`` when ``pgrep`` is unavailable, so a
    missing binary can never be misread as "no Xray core is running" — that
    misreading previously caused the health check to restart a perfectly
    healthy core on every tick.
    """
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


class XRayCore:
    def __init__(self,
                 executable_path: str = "/usr/bin/xray",
                 assets_path: str = "/usr/share/xray"):
        self.executable_path = executable_path
        self.assets_path = assets_path

        self.version = self.get_version()
        self.process = None
        self.restarting = False

        # Bumped on every (re)start so the serving layer can detect that the
        # live core was replaced and rebuild its registered-user registry from
        # the exact config the core booted with.
        self.config_generation = 0
        self.last_config = None
        self.started_at: float | None = None
        self._last_restart_at: float | None = None
        self.startup_error: str | None = None
        self.failed_port: int | None = None
        self.failed_inbound_tag: str | None = None

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
        output = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode('utf-8')
        m = re.match(r'^Xray (\d+\.\d+\.\d+)', output)
        if m:
            return m.groups()[0]

    def get_x25519(self, private_key: str = None):
        cmd = [self.executable_path, "x25519"]
        if private_key:
            cmd.extend(['-i', private_key])
        output = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode('utf-8')
        private = public = None
        for line in output.splitlines():
            line = line.strip()
            if line.startswith("Private key:"):
                private = line.split(":", 1)[1].strip()
            elif line.startswith("Public key:"):
                public = line.split(":", 1)[1].strip()
            elif line.startswith("PrivateKey:"):
                private = line.split(":", 1)[1].strip()
            elif line.startswith("Password (PublicKey):"):
                public = line.split(":", 1)[1].strip()
        if private and public:
            return {"private_key": private, "public_key": public}
        return None

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
                    rc = self.process.poll() if self.process else None
                    if rc not in (None, 0):
                        tail = list(self._logs_buffer)[-20:]
                        self._record_startup_failure(tail)
                        logger.warning(
                            "Xray core exited with code %s; recent logs: %s",
                            rc,
                            " | ".join(tail) if tail else "(empty)",
                        )
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
                    rc = self.process.poll() if self.process else None
                    if rc not in (None, 0):
                        tail = list(self._logs_buffer)[-20:]
                        self._record_startup_failure(tail)
                        logger.warning(
                            "Xray core exited with code %s; recent logs: %s",
                            rc,
                            " | ".join(tail) if tail else "(empty)",
                        )
                    break

        if DEBUG:
            threading.Thread(target=capture_and_debug_log).start()
        else:
            threading.Thread(target=capture_only).start()

    def _clear_startup_failure(self) -> None:
        self.startup_error = None
        self.failed_port = None
        self.failed_inbound_tag = None

    def _record_startup_failure(self, tail: list[str]) -> None:
        from app.xray.inbound_ports import parse_bind_failure

        inbounds = None
        if self.last_config is not None:
            inbounds = self.last_config.get("inbounds")
        port, tag, msg = parse_bind_failure(tail, inbounds)
        self.startup_error = msg
        self.failed_port = port
        self.failed_inbound_tag = tag

    @contextmanager
    def get_logs(self):
        buf = deque(self._logs_buffer, maxlen=100)
        buf_id = id(buf)
        try:
            self._temp_log_buffers[buf_id] = buf
            yield buf
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
        with _lifecycle_lock:
            if self.started is True:
                # Orphan reclaim / duplicate startup — restart converges ports + API.
                self.restart(config, force=True)
                return

            self._prepare_listen_ports(config)
            self._start_process(config)

    def _start_process(self, config: XRayConfig):
        """Spawn Xray after listen ports are free (caller holds lifecycle lock)."""

        # The local core is the panel's own tunnel endpoint (node_id=None):
        # fold in any tunnel fragments where the panel is the relay or exit.
        try:
            from app.tunnel.inject import apply_endpoint_tunnels
            config = apply_endpoint_tunnels(config, None)
        except Exception:
            pass

        try:
            from app.services.edge_proxy import apply_edge_runtime_to_config
            config = apply_edge_runtime_to_config(config)
        except Exception:
            logger.exception("edge runtime override failed")

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
            stderr=subprocess.STDOUT,
            stdout=subprocess.PIPE,
            universal_newlines=True
        )
        self.process.stdin.write(config.to_json())
        self.process.stdin.flush()
        self.process.stdin.close()

        # Record the booted config so the serving layer can reconcile its
        # registered-user registry against reality after any restart path.
        self.last_config = config
        self.config_generation += 1

        logger.warning(f"Xray core {self.version} started")
        self._clear_startup_failure()
        self.started_at = time.time()

        try:
            from app.billing_guard import reset_billing_guard_state

            reset_billing_guard_state()
        except Exception:
            pass

        self.__capture_process_logs()

        # execute on start functions
        for func in self._on_start_funcs:
            threading.Thread(target=func).start()

    def stop(self):
        with _lifecycle_lock:
            self._stop_process()

    def _stop_process(self):
        """Terminate tracked Xray (caller holds lifecycle lock)."""
        proc = self.process
        if not proc:
            return

        try:
            proc.terminate()
            proc.wait(timeout=XRAY_RESTART_STOP_TIMEOUT)
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
        self.started_at = None
        logger.warning("Xray core stopped")

        # execute on stop functions
        for func in self._on_stop_funcs:
            threading.Thread(target=func).start()

    @staticmethod
    def _self_container_id() -> str | None:
        """Resolve this container's own ID via the mounted docker.sock.

        The panel runs unprivileged (``runuser -u nexuspanel``) while stray
        processes created by out-of-band root ``docker exec`` sessions (e.g. a
        one-off admin script) are owned by root — ``os.kill``/shell ``kill``
        both fail with EPERM on those since the panel's own uid lacks CAP_KILL
        for them (host PID namespace does not bypass the standard signal
        permission check). ``docker exec --user root`` on this same
        container asks the (root) Docker daemon to do the killing instead.
        """
        try:
            out = subprocess.run(
                [
                    "docker", "ps", "-q",
                    "--filter", "label=com.docker.compose.service=nexuspanel",
                ],
                capture_output=True, text=True, timeout=5,
            )
        except Exception:
            return None
        cid = out.stdout.strip().splitlines()[0].strip() if out.stdout.strip() else None
        return cid or None

    @staticmethod
    def _privileged_kill_pids(pids: list[int], *, sig: int) -> None:
        """Last resort: escalate via ``docker exec --user root`` + docker.sock."""
        cid = XRayCore._self_container_id()
        if not cid:
            return
        sig_num = int(sig)
        for pid in pids:
            try:
                subprocess.run(
                    ["docker", "exec", "--user", "root", cid, "kill", f"-{sig_num}", str(pid)],
                    check=False,
                    capture_output=True,
                    timeout=8,
                )
            except Exception as exc:
                logger.warning("privileged kill (sig=%s) for pid=%s failed: %s", sig_num, pid, exc)

    @staticmethod
    def _shell_kill_pids(pids: list[int], *, sig: int = signal.SIGTERM) -> None:
        """Fallback when ``os.kill`` fails (e.g. permission quirks in container)."""
        sig_name = "TERM" if sig == signal.SIGTERM else "KILL"
        still_denied: list[int] = []
        for pid in pids:
            try:
                result = subprocess.run(
                    ["kill", f"-{sig_name}", str(pid)],
                    check=False,
                    capture_output=True,
                    timeout=5,
                    text=True,
                )
                if result.returncode != 0 and "not permitted" in (result.stderr or "").lower():
                    still_denied.append(pid)
            except Exception as exc:
                logger.warning("shell kill %s for pid=%s failed: %s", sig_name, pid, exc)
                still_denied.append(pid)
        if still_denied:
            logger.warning(
                "Permission denied killing pid(s) %s (likely root-owned orphan from an "
                "out-of-band docker exec) — escalating via docker exec --user root",
                still_denied,
            )
            XRayCore._privileged_kill_pids(still_denied, sig=sig)

    @staticmethod
    def _terminate_pids(pids: list[int], *, wait_sec: float = 5.0) -> None:
        """SIGTERM, wait for exit, then SIGKILL any survivors."""
        if not pids:
            return
        alive = list(dict.fromkeys(pids))
        denied: list[int] = []
        for pid in alive:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except (PermissionError, OSError):
                denied.append(pid)
        if denied:
            XRayCore._shell_kill_pids(denied, sig=signal.SIGTERM)
        deadline = time.monotonic() + wait_sec
        while time.monotonic() < deadline:
            still: list[int] = []
            for pid in alive:
                try:
                    os.kill(pid, 0)
                    still.append(pid)
                except ProcessLookupError:
                    pass
                except (PermissionError, OSError):
                    still.append(pid)
            if not still:
                return
            time.sleep(0.1)
            alive = still
        kill_denied: list[int] = []
        for pid in alive:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except (PermissionError, OSError):
                kill_denied.append(pid)
        if kill_denied:
            XRayCore._shell_kill_pids(kill_denied, sig=signal.SIGKILL)
        time.sleep(0.2)

    @staticmethod
    def _kill_stale_stdin_xray(keep_pid: int | None = None):
        """Ensure no orphan ``xray run -config stdin`` survives a restart."""
        from config import XRAY_EXECUTABLE_PATH

        pids = find_stdin_xray_pids(XRAY_EXECUTABLE_PATH)
        targets = [pid for pid in pids if not (keep_pid and pid == keep_pid)]
        XRayCore._terminate_pids(targets)

    def _free_listen_ports(self, ports: list[int]) -> None:
        """Drop panel Xray processes still bound to product inbound ports."""
        if not ports:
            return
        from config import XRAY_EXECUTABLE_PATH
        from app.xray.inbound_ports import listener_pids_by_port

        stdin_pids = set(find_stdin_xray_pids(XRAY_EXECUTABLE_PATH))
        by_port = listener_pids_by_port()
        blockers: list[int] = []
        for port in ports:
            for name, pid in by_port.get(port, []):
                if pid is None:
                    continue
                if pid in stdin_pids or str(name).lower() == "xray":
                    blockers.append(pid)
        self._terminate_pids(blockers)

    def _prepare_listen_ports(self, config: XRayConfig) -> None:
        with _lifecycle_lock:
            if getattr(self, "restarting", False):
                return
            self._prepare_listen_ports_unlocked(config)

    def _prepare_listen_ports_unlocked(self, config: XRayConfig) -> None:
        from app.xray.inbound_ports import product_inbound_ports

        keep_pid = self.process.pid if self.process and self.process.poll() is None else None
        ports = product_inbound_ports(config.get("inbounds"))
        self._kill_stale_stdin_xray(keep_pid=keep_pid)
        self._free_listen_ports(ports)
        if not ports:
            return
        from app.xray.inbound_ports import listener_pids_by_port

        deadline = time.monotonic() + XRAY_RESTART_PORT_RECLAIM_TIMEOUT
        while time.monotonic() < deadline:
            busy = [p for p in ports if listener_pids_by_port().get(p)]
            if not busy:
                return
            self._free_listen_ports(busy)
            time.sleep(0.15)

    def restart(self, config: XRayConfig, *, force: bool = False):
        with _lifecycle_lock:
            if self.restarting is True:
                return

            now = time.time()
            if (
                not force
                and self._last_restart_at is not None
                and (now - self._last_restart_at) < _HEALTH_RESTART_COOLDOWN_SEC
            ):
                logger.debug("Skipping Xray restart — cooldown active")
                return

            try:
                self.restarting = True
                logger.warning("Restarting Xray core...")
                self._stop_process()
                self._prepare_listen_ports_unlocked(config)
                self._start_process(config)
                self._last_restart_at = time.time()
            finally:
                self.restarting = False

    def in_health_restart_cooldown(self, now: float | None = None) -> bool:
        """True briefly after a restart so health checks don't pile on."""
        last = self._last_restart_at
        if last is None:
            return False
        ts = now if now is not None else time.time()
        return (ts - last) < _HEALTH_RESTART_COOLDOWN_SEC

    def on_start(self, func: callable):
        self._on_start_funcs.append(func)
        return func

    def on_stop(self, func: callable):
        self._on_stop_funcs.append(func)
        return func
