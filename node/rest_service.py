import asyncio
import hmac
import json
import time
from typing import Optional
from uuid import UUID, uuid4

from fastapi import (APIRouter, Body, FastAPI, HTTPException, Request,
                     WebSocket, status)
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.websockets import WebSocketDisconnect

from config import XRAY_ASSETS_PATH, XRAY_EXECUTABLE_PATH
from logger import logger
from singbox import SingBoxManager, SingBoxSpec
from speed_limit import SpeedLimitManager, peer_limits_from_spec, port_limits_from_spec
from wireguard import WireGuardManager, WireGuardSpec
from wg_autoscale import InterfaceSpec, WireGuardAutoScale
from xray import XRayConfig, XRayCore

app = FastAPI()


@app.exception_handler(RequestValidationError)
def validation_exception_handler(request: Request, exc: RequestValidationError):
    details = {}
    for error in exc.errors():
        details[error["loc"][-1]] = error.get("msg")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=jsonable_encoder({"detail": details}),
    )


class Service(object):
    def __init__(self):
        self.router = APIRouter()

        self.connected = False
        self.client_ip = None
        self.session_id = None
        self.core = XRayCore(
            executable_path=XRAY_EXECUTABLE_PATH,
            assets_path=XRAY_ASSETS_PATH
        )
        self.core_version = self.core.get_version()
        self.config = None
        self.wg = WireGuardManager()
        self.wg_autoscale = WireGuardAutoScale()
        self.singbox = SingBoxManager()
        self.speed_limit = SpeedLimitManager()

        self.router.add_api_route("/", self.base, methods=["POST"])
        self.router.add_api_route("/ping", self.ping, methods=["POST"])
        self.router.add_api_route("/connect", self.connect, methods=["POST"])
        self.router.add_api_route("/disconnect", self.disconnect, methods=["POST"])
        self.router.add_api_route("/start", self.start, methods=["POST"])
        self.router.add_api_route("/stop", self.stop, methods=["POST"])
        self.router.add_api_route("/restart", self.restart, methods=["POST"])

        # WireGuard product endpoints (Phase 11). The panel pushes a declarative
        # spec and reads back per-peer transfer counters for central accounting.
        self.router.add_api_route("/wg/apply", self.wg_apply, methods=["POST"])
        self.router.add_api_route("/wg/apply-specs", self.wg_apply_specs, methods=["POST"])
        self.router.add_api_route("/wg/open-udp-ports", self.wg_open_udp_ports, methods=["POST"])
        self.router.add_api_route("/wg/transfer", self.wg_transfer, methods=["POST"])
        self.router.add_api_route("/wg/down", self.wg_down, methods=["POST"])
        self.router.add_api_route("/wg/amnezia-available", self.wg_amnezia_available, methods=["POST"])
        # RPyC-parity endpoints (Phase 11.3 fixed a "connect once, reconnect
        # never" mobile bug by adding these on the RPyC side only —
        # rpyc_service.py: wg_reconcile_awg_endpoints/wg_prepare_peer_for_connect/
        # wg_flush_stale_peers/wg_recover_awg_interface/wg_flush_bad_endpoints.
        # REST-detected nodes never got them, so the same bug silently came
        # back on any node the panel talks to over REST (see AUDIT_FINDINGS.md H1).
        self.router.add_api_route("/wg/reconcile-endpoints", self.wg_reconcile_endpoints, methods=["POST"])
        self.router.add_api_route("/wg/prepare-peer", self.wg_prepare_peer, methods=["POST"])
        self.router.add_api_route("/wg/flush-stale-peers", self.wg_flush_stale_peers, methods=["POST"])
        self.router.add_api_route("/wg/recover-interface", self.wg_recover_interface, methods=["POST"])
        self.router.add_api_route("/wg/flush-bad-endpoints", self.wg_flush_bad_endpoints, methods=["POST"])
        self.router.add_api_route("/wg/autoscale/create-interface", self.wg_autoscale_create_interface, methods=["POST"])
        self.router.add_api_route("/wg/autoscale/hot-add", self.wg_autoscale_hot_add, methods=["POST"])
        self.router.add_api_route("/wg/autoscale/toggle", self.wg_autoscale_toggle, methods=["POST"])
        self.router.add_api_route("/wg/autoscale/dump", self.wg_autoscale_dump, methods=["POST"])
        self.router.add_api_route("/wg/autoscale/transfer", self.wg_autoscale_transfer, methods=["POST"])
        # sing-box product endpoints (Hysteria2/TUIC). Same declarative model:
        # the panel pushes the full inbound+user spec and reads per-user traffic.
        self.router.add_api_route("/singbox/apply", self.singbox_apply, methods=["POST"])
        self.router.add_api_route("/singbox/transfer", self.singbox_transfer, methods=["POST"])
        self.router.add_api_route("/singbox/down", self.singbox_down, methods=["POST"])
        self.router.add_api_route("/singbox/tls/status", self.singbox_tls_status, methods=["POST"])
        self.router.add_api_route("/xray/upgrade", self.xray_upgrade, methods=["POST"])
        self.router.add_api_route("/outbound/test", self.outbound_test, methods=["POST"])

        self.router.add_websocket_route("/logs", self.logs)

    def match_session_id(self, session_id: UUID):
        if session_id != self.session_id:
            raise HTTPException(
                status_code=403,
                detail="Session ID mismatch."
            )
        return True

    def response(self, **kwargs):
        return {
            "connected": self.connected,
            "started": self.core.started,
            "core_version": self.core_version,
            **kwargs
        }

    def base(self):
        return self.response()

    def connect(self, request: Request):
        self.session_id = uuid4()
        self.client_ip = request.client.host

        if self.connected:
            logger.warning(
                f'New connection from {self.client_ip}, Core control access was taken away from previous client.')
            if self.core.started:
                try:
                    self.core.stop()
                except RuntimeError:
                    pass

        self.connected = True
        logger.info(f'{self.client_ip} connected, Session ID = "{self.session_id}".')

        return self.response(
            session_id=self.session_id
        )

    def disconnect(self):
        if self.connected:
            logger.info(f'{self.client_ip} disconnected, Session ID = "{self.session_id}".')

        self.session_id = None
        self.client_ip = None
        self.connected = False

        if self.core.started:
            try:
                self.core.stop()
            except RuntimeError:
                pass

        return self.response()

    def ping(self, session_id: UUID = Body(embed=True)):
        self.match_session_id(session_id)
        return {}

    def start(self, session_id: UUID = Body(embed=True), config: str = Body(embed=True)):
        self.match_session_id(session_id)

        try:
            config = XRayConfig(config, self.client_ip)
        except json.decoder.JSONDecodeError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "config": f'Failed to decode config: {exc}'
                }
            )

        with self.core.get_logs() as logs:
            try:
                self.core.start(config)

                start_time = time.time()
                end_time = start_time + 3
                last_log = ''
                while time.time() < end_time:
                    while logs:
                        log = logs.popleft()
                        if log:
                            last_log = log
                        if f'Xray {self.core_version} started' in log:
                            break
                    time.sleep(0.1)

            except Exception as exc:
                logger.error(f"Failed to start core: {exc}")
                raise HTTPException(
                    status_code=503,
                    detail=str(exc)
                )

        if not self.core.started:
            raise HTTPException(
                status_code=503,
                detail=last_log
            )

        return self.response()

    def stop(self, session_id: UUID = Body(embed=True)):
        self.match_session_id(session_id)

        try:
            self.core.stop()

        except RuntimeError:
            pass

        return self.response()

    def restart(self, session_id: UUID = Body(embed=True), config: str = Body(embed=True)):
        self.match_session_id(session_id)

        try:
            config = XRayConfig(config, self.client_ip)
        except json.decoder.JSONDecodeError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "config": f'Failed to decode config: {exc}'
                }
            )

        try:
            with self.core.get_logs() as logs:
                self.core.restart(config)

                start_time = time.time()
                end_time = start_time + 3
                last_log = ''
                while time.time() < end_time:
                    while logs:
                        log = logs.popleft()
                        if log:
                            last_log = log
                        if f'Xray {self.core_version} started' in log:
                            break
                    time.sleep(0.1)

        except Exception as exc:
            logger.error(f"Failed to restart core: {exc}")
            raise HTTPException(
                status_code=503,
                detail=str(exc)
            )

        if not self.core.started:
            raise HTTPException(
                status_code=503,
                detail=last_log
            )

        return self.response()

    def xray_upgrade(self, session_id: UUID = Body(embed=True), tag: str = Body(embed=True)):
        self.match_session_id(session_id)
        from xray_upgrade import install_xray_release

        if self.core.started:
            try:
                self.core.stop()
            except RuntimeError:
                pass

        try:
            version = install_xray_release(tag)
        except Exception as exc:
            logger.error("Xray upgrade failed: %s", exc)
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        self.core = XRayCore(
            executable_path=XRAY_EXECUTABLE_PATH,
            assets_path=XRAY_ASSETS_PATH,
        )
        self.core_version = self.core.get_version()
        return self.response(version=version)

    def outbound_test(self, session_id: UUID = Body(embed=True), outbound: dict = Body(embed=True)):
        self.match_session_id(session_id)
        from outbound_test import test_outbound_tcp

        return test_outbound_tcp(outbound)

    def wg_apply(self, session_id: UUID = Body(embed=True), spec: dict = Body(embed=True)):
        self.match_session_id(session_id)
        try:
            wg_spec = WireGuardSpec.from_dict(spec)
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail={"spec": f"Invalid WireGuard spec: {exc}"})
        try:
            # apply_specs also opens UDP INPUT + egress NAT.
            self.wg.apply_specs([wg_spec])
            limits = peer_limits_from_spec(spec)
            if limits:
                self.speed_limit.apply_wireguard(wg_spec.interface, limits)
        except Exception as exc:
            logger.error(f"Failed to apply WireGuard spec: {exc}")
            raise HTTPException(status_code=503, detail=str(exc))
        return {"interface": wg_spec.interface, "peers": len(wg_spec.peers)}

    def wg_apply_specs(self, session_id: UUID = Body(embed=True), specs: list = Body(embed=True)):
        self.match_session_id(session_id)
        try:
            wg_specs = [WireGuardSpec.from_dict(item) for item in (specs or [])]
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail={"specs": f"Invalid WireGuard specs: {exc}"})
        if not wg_specs:
            raise HTTPException(status_code=422, detail="At least one WireGuard spec is required")
        try:
            self.wg.apply_specs(wg_specs)
            for raw, wg_spec in zip(specs or [], wg_specs):
                limits = peer_limits_from_spec(raw)
                if limits:
                    self.speed_limit.apply_wireguard(wg_spec.interface, limits)
        except Exception as exc:
            logger.error(f"Failed to apply WireGuard specs: {exc}")
            raise HTTPException(status_code=503, detail=str(exc))
        return {"interfaces": [s.interface for s in wg_specs], "peers": sum(len(s.peers) for s in wg_specs)}

    def wg_open_udp_ports(self, session_id: UUID = Body(embed=True), ports: list = Body(embed=True)):
        self.match_session_id(session_id)
        try:
            wanted = [int(p) for p in (ports or []) if p]
            self.wg.open_udp_ports(wanted)
        except Exception as exc:
            logger.error(f"Failed to open UDP ports: {exc}")
            raise HTTPException(status_code=503, detail=str(exc))
        return {"ports": wanted, "opened": len(wanted)}

    def wg_transfer(self, session_id: UUID = Body(embed=True), interface: str = Body(embed=True)):
        self.match_session_id(session_id)
        try:
            return {"transfer": self.wg.get_transfer(interface)}
        except Exception as exc:
            logger.error(f"Failed to read WireGuard transfer: {exc}")
            raise HTTPException(status_code=503, detail=str(exc))

    def wg_down(self, session_id: UUID = Body(embed=True), interface: str = Body(embed=True)):
        self.match_session_id(session_id)
        try:
            self.wg.teardown(interface)
        except Exception as exc:
            logger.error(f"Failed to tear down WireGuard interface: {exc}")
            raise HTTPException(status_code=503, detail=str(exc))
        return {"interface": interface, "down": True}

    def wg_amnezia_available(self, session_id: UUID = Body(embed=True)):
        self.match_session_id(session_id)
        return {"available": self.wg.amnezia_available()}

    def wg_reconcile_endpoints(
        self,
        session_id: UUID = Body(embed=True),
        interface: str = Body(embed=True),
        stale_sec: int = Body(embed=True, default=180),
    ):
        self.match_session_id(session_id)
        try:
            cleared = self.wg.reconcile_awg_endpoints(interface, stale_sec=int(stale_sec))
        except Exception as exc:
            logger.error(f"Failed to reconcile AWG endpoints: {exc}")
            raise HTTPException(status_code=503, detail=str(exc))
        return {"interface": interface, "cleared": cleared}

    def wg_flush_bad_endpoints(
        self, session_id: UUID = Body(embed=True), interface: str = Body(embed=True)
    ):
        self.match_session_id(session_id)
        try:
            cleared = self.wg.flush_bad_endpoints(interface)
        except Exception as exc:
            logger.error(f"Failed to flush bad AWG endpoints: {exc}")
            raise HTTPException(status_code=503, detail=str(exc))
        return {"interface": interface, "cleared": cleared}

    def wg_prepare_peer(
        self,
        session_id: UUID = Body(embed=True),
        interface: str = Body(embed=True),
        public_key: str = Body(embed=True),
    ):
        self.match_session_id(session_id)
        try:
            prepared = self.wg.prepare_peer_for_connect(interface, public_key)
        except Exception as exc:
            logger.error(f"Failed to prepare AWG peer for connect: {exc}")
            raise HTTPException(status_code=503, detail=str(exc))
        return {"interface": interface, "public_key": public_key, "prepared": bool(prepared)}

    def wg_flush_stale_peers(
        self,
        session_id: UUID = Body(embed=True),
        interface: str = Body(embed=True),
        max_age_sec: int = Body(embed=True, default=35),
        idle_sec: int = Body(embed=True, default=5),
        traffic_only: bool = Body(embed=True, default=True),
    ):
        self.match_session_id(session_id)
        try:
            flushed = self.wg.flush_stale_peers(
                interface,
                max_age_sec=int(max_age_sec),
                idle_sec=int(idle_sec),
                traffic_only=bool(traffic_only),
            )
        except Exception as exc:
            logger.error(f"Failed to flush stale WG peers: {exc}")
            raise HTTPException(status_code=503, detail=str(exc))
        return {"interface": interface, "flushed": flushed}

    def wg_recover_interface(
        self, session_id: UUID = Body(embed=True), interface: str = Body(embed=True)
    ):
        self.match_session_id(session_id)
        try:
            recovered = self.wg.recover_awg_interface(interface)
        except Exception as exc:
            logger.error(f"Failed to recover AWG interface: {exc}")
            raise HTTPException(status_code=503, detail=str(exc))
        return {"interface": interface, "recovered": bool(recovered)}

    def wg_autoscale_create_interface(self, session_id: UUID = Body(embed=True), spec: dict = Body(embed=True)):
        self.match_session_id(session_id)
        try:
            self.wg_autoscale.create_interface(InterfaceSpec.from_dict(spec))
        except Exception as exc:
            logger.error(f"Failed to create auto-scale WG interface: {exc}")
            raise HTTPException(status_code=503, detail=str(exc))
        return {"interface": spec.get("name"), "created": True}

    def wg_autoscale_hot_add(
        self,
        session_id: UUID = Body(embed=True),
        interface: str = Body(embed=True),
        public_key: str = Body(embed=True),
        allowed_ips: str = Body(embed=True),
        preshared_key: Optional[str] = Body(embed=True, default=None),
    ):
        self.match_session_id(session_id)
        try:
            self.wg_autoscale.hot_add_peer(
                interface, public_key, allowed_ips, preshared_key=preshared_key
            )
        except Exception as exc:
            logger.error(f"Failed to hot-add WG peer: {exc}")
            raise HTTPException(status_code=503, detail=str(exc))
        return {"interface": interface, "public_key": public_key}

    def wg_autoscale_toggle(
        self,
        session_id: UUID = Body(embed=True),
        interface: str = Body(embed=True),
        public_key: str = Body(embed=True),
        active: bool = Body(embed=True),
        allowed_ips: str = Body(embed=True),
        preshared_key: Optional[str] = Body(embed=True, default=None),
    ):
        self.match_session_id(session_id)
        try:
            self.wg_autoscale.toggle_peer(
                interface,
                public_key,
                active=active,
                allowed_ips=allowed_ips,
                preshared_key=preshared_key,
            )
        except Exception as exc:
            logger.error(f"Failed to toggle WG peer: {exc}")
            raise HTTPException(status_code=503, detail=str(exc))
        return {"interface": interface, "public_key": public_key, "active": active}

    def wg_autoscale_dump(self, session_id: UUID = Body(embed=True)):
        self.match_session_id(session_id)
        return {"dump": self.wg_autoscale.show_dump_all()}

    def wg_autoscale_transfer(
        self, session_id: UUID = Body(embed=True), interface: str = Body(embed=True)
    ):
        self.match_session_id(session_id)
        return {"transfer": self.wg_autoscale.get_transfer(interface)}

    def singbox_apply(self, session_id: UUID = Body(embed=True), spec: dict = Body(embed=True)):
        self.match_session_id(session_id)
        try:
            sb_spec = SingBoxSpec.from_dict(spec)
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail={"spec": f"Invalid sing-box spec: {exc}"})
        if not self.singbox.available():
            raise HTTPException(status_code=503, detail="sing-box binary not installed on node")
        try:
            self.singbox.apply(sb_spec)
        except Exception as exc:
            logger.error(f"Failed to apply sing-box spec: {exc}")
            raise HTTPException(status_code=503, detail=str(exc))
        return {"inbounds": len(sb_spec.inbounds), "running": self.singbox.is_running()}

    def singbox_transfer(self, session_id: UUID = Body(embed=True)):
        self.match_session_id(session_id)
        try:
            return {"transfer": self.singbox.get_transfer()}
        except Exception as exc:
            logger.error(f"Failed to read sing-box transfer: {exc}")
            raise HTTPException(status_code=503, detail=str(exc))

    def singbox_down(self, session_id: UUID = Body(embed=True)):
        self.match_session_id(session_id)
        try:
            self.singbox.stop()
        except Exception as exc:
            logger.error(f"Failed to stop sing-box: {exc}")
            raise HTTPException(status_code=503, detail=str(exc))
        return {"down": True}

    def singbox_tls_status(
        self,
        session_id: UUID = Body(embed=True),
        certificate_path: str = Body(embed=True, default="/var/lib/nexuspanel-node/tls/cert.pem"),
    ):
        self.match_session_id(session_id)
        from tls_inspect import inspect_cert_file

        return inspect_cert_file(certificate_path)

    async def logs(self, websocket: WebSocket):
        session_id = websocket.query_params.get('session_id')
        interval = websocket.query_params.get('interval')

        try:
            session_id = UUID(session_id)
            if session_id != self.session_id:
                return await websocket.close(reason="Session ID mismatch.", code=4403)

        except ValueError:
            return await websocket.close(reason="session_id should be a valid UUID.", code=4400)

        if interval:
            try:
                interval = float(interval)

            except ValueError:
                return await websocket.close(reason="Invalid interval value.", code=4400)

            if interval > 10:
                return await websocket.close(reason="Interval must be more than 0 and at most 10 seconds.", code=4400)

        await websocket.accept()

        cache = ''
        last_sent_ts = 0
        with self.core.get_logs() as logs:
            while session_id == self.session_id:
                if interval and time.time() - last_sent_ts >= interval and cache:
                    try:
                        await websocket.send_text(cache)
                    except (WebSocketDisconnect, RuntimeError):
                        break
                    cache = ''
                    last_sent_ts = time.time()

                if not logs:
                    try:
                        await asyncio.wait_for(websocket.receive(), timeout=0.2)
                        continue
                    except asyncio.TimeoutError:
                        continue
                    except (WebSocketDisconnect, RuntimeError):
                        break

                log = logs.popleft()

                if interval:
                    cache += f'{log}\n'
                    continue

                try:
                    await websocket.send_text(log)
                except (WebSocketDisconnect, RuntimeError):
                    break

        await websocket.close()


@app.middleware("http")
async def node_control_secret_middleware(request: Request, call_next):
    # NOTE: must be the flat top-level `config` module — this file runs
    # in-place as /code/rest_service.py on the node (no `node` package
    # exists there). `from node.config import ...` raised ModuleNotFoundError
    # on every single POST request in production, turning into an
    # uncaught 500 before the request ever reached a route handler —
    # i.e. NODE_CONTROL_SECRET silently broke ALL REST node control
    # (found while live-verifying H1; see AUDIT_FINDINGS.md).
    from config import NODE_CONTROL_SECRET

    if NODE_CONTROL_SECRET and request.method in ("POST", "PUT", "PATCH", "DELETE"):
        provided = request.headers.get("X-Nexus-Control-Secret", "")
        if not hmac.compare_digest(provided, NODE_CONTROL_SECRET):
            return JSONResponse(status_code=403, content={"detail": "Invalid node control secret"})
    return await call_next(request)


service = Service()
app.include_router(service.router)
