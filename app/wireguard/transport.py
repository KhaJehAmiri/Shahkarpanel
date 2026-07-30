"""Panel -> node transport for native WireGuard control (Phase 11.3).

Drives the node agent's ``/wg/apply`` | ``/wg/transfer`` | ``/wg/down`` over
whichever channel the node already speaks — REST (``ReSTXRayNode``) or RPyC
(``RPyCXRayNode``) — reusing the same authenticated/SSL connection the panel
holds for Xray. ``client_for_node`` auto-detects, mirroring ``XRayNode``.

The clients only depend on a tiny duck-typed surface so they are unit testable
with fakes (no live node required).
"""
from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator, List, Optional, Sequence

logger = logging.getLogger("shahkar-wg")


class WireGuardTransportError(Exception):
    pass


# Full ``wg syncconf`` of thousands of peers (often ×2 for plain+AWG) is I/O
# heavy. Old formula ``30 + n/20`` gave ~180s at 3k — too tight once dual-stack
# and PSK tempfile work are counted. Floor 120s, ~125ms/peer, cap 15min.
_APPLY_TIMEOUT_FLOOR_SEC = 120
_APPLY_TIMEOUT_CEILING_SEC = 900
_APPLY_TIMEOUT_BASE_SEC = 90

# Above this peer count, a single RPyC ``syncconf`` payload routinely dies with
# ``stream has been closed`` on flaky Iran↔abroad links. Empty iface bring-up
# + ``wg_apply_batch`` chunks keeps membership automatic and resumable.
WG_APPLY_RPC_CHUNK = 150
WG_APPLY_BATCH_TIMEOUT_SEC = 90


def wg_apply_timeout_sec(peer_count: int, *, minimum: int = 30) -> int:
    """Seconds to wait for a full peer-set apply (REST or RPyC).

    ``peer_count`` should be the sum of peers across all specs in one call
    (e.g. plain + Amnezia).
    """
    n = max(0, int(peer_count or 0))
    scaled = _APPLY_TIMEOUT_BASE_SEC + (n // 8)
    return int(
        max(
            _APPLY_TIMEOUT_FLOOR_SEC,
            min(_APPLY_TIMEOUT_CEILING_SEC, max(int(minimum), scaled)),
        )
    )


def _spec_to_batch_rows(peers: Sequence[dict]) -> List[dict]:
    """Convert declarative apply-spec peers into ``wg_apply_batch`` rows."""
    rows: List[dict] = []
    for p in peers or []:
        if not isinstance(p, dict):
            continue
        pk = p.get("public_key")
        if not pk:
            continue
        allowed = p.get("allowed_ips") or []
        if isinstance(allowed, (list, tuple)):
            allowed_s = ",".join(str(a) for a in allowed if a)
        else:
            allowed_s = str(allowed or "")
        if not allowed_s:
            continue
        rows.append(
            {
                "public_key": pk,
                "allowed_ips": allowed_s,
                "preshared_key": p.get("preshared_key"),
                "active": True,
                "user_id": int(p.get("user_id") or 0),
            }
        )
    return rows


def _apply_specs_chunked(
    *,
    apply_direct: Callable[[list, int], None],
    apply_batch: Callable[..., Any],
    specs: list,
    timeout: int,
    chunk_size: int = WG_APPLY_RPC_CHUNK,
) -> None:
    """Bring each interface up, then stream peers in small ``apply_batch`` calls.

    ``apply_direct`` receives ``(specs, timeout)`` and must perform a normal
    full ``syncconf`` (used for empty/small specs). Large peer sets never go
    through one RPyC payload — that is what dropped tunnel-exit membership.
    """
    for raw in specs or []:
        spec = dict(raw or {})
        peers = list(spec.get("peers") or [])
        iface = spec.get("interface") or ""
        if not iface:
            continue
        if len(peers) <= chunk_size:
            apply_direct([spec], timeout)
            continue

        empty = dict(spec)
        empty["peers"] = []
        # Empty syncconf creates/resets the iface. Brief membership gap is
        # acceptable vs permanently empty exits after agent recreate.
        apply_direct([empty], max(60, int(timeout)))
        rows = _spec_to_batch_rows(peers)
        generation = int(time.time())
        total = len(rows)
        for i in range(0, total, chunk_size):
            chunk = rows[i : i + chunk_size]
            cursor = i + len(chunk)
            apply_batch(
                interface=iface,
                generation=generation,
                cursor=cursor,
                peers=chunk,
                removes=[],
                timeout=WG_APPLY_BATCH_TIMEOUT_SEC,
            )
            logger.info(
                "WG chunked apply iface=%s progress=%s/%s",
                iface,
                cursor,
                total,
            )


def wg_apply_timeout_sec(peer_count: int, *, minimum: int = 30) -> int:
    """Seconds to wait for a full peer-set apply (REST or RPyC).

    ``peer_count`` should be the sum of peers across all specs in one call
    (e.g. plain + Amnezia).
    """
    n = max(0, int(peer_count or 0))
    scaled = _APPLY_TIMEOUT_BASE_SEC + (n // 8)
    return int(
        max(
            _APPLY_TIMEOUT_FLOOR_SEC,
            min(_APPLY_TIMEOUT_CEILING_SEC, max(int(minimum), scaled)),
        )
    )


@contextmanager
def _rpyc_sync_timeout(conn, timeout: float) -> Iterator[None]:
    """Temporarily raise RPyC ``sync_request_timeout``, then always restore.

    Mutating the shared connection config without restore would leave later
    health checks / usage RPCs waiting minutes on a wedged channel.
    """
    if conn is None or not hasattr(conn, "_config"):
        yield
        return
    cfg = conn._config
    prev = cfg.get("sync_request_timeout")
    cfg["sync_request_timeout"] = float(timeout)
    try:
        yield
    finally:
        if prev is None:
            cfg.pop("sync_request_timeout", None)
        else:
            cfg["sync_request_timeout"] = prev


class AutoScaleWireGuardMixin:
    """Node agent RPC/REST surface for WireGuard auto-scale."""

    def autoscale_create_interface(self, spec: dict, timeout: int = 30) -> None:
        raise NotImplementedError

    def autoscale_hot_add_peer(
        self,
        interface: str,
        public_key: str,
        allowed_ips: str,
        *,
        preshared_key: Optional[str] = None,
        timeout: int = 15,
    ) -> None:
        raise NotImplementedError

    def autoscale_toggle_peer(
        self,
        interface: str,
        public_key: str,
        *,
        active: bool,
        allowed_ips: str,
        preshared_key: Optional[str] = None,
        timeout: int = 15,
    ) -> None:
        raise NotImplementedError

    def autoscale_show_dump(self, timeout: int = 15) -> list:
        raise NotImplementedError

    def autoscale_transfer(self, interface: str, timeout: int = 10) -> dict:
        raise NotImplementedError


class RESTWireGuardClient(AutoScaleWireGuardMixin):
    """Talks to the node agent's ``/wg/*`` REST routes via a ReST node's
    ``make_request`` (which injects ``session_id`` and client-cert auth)."""

    def __init__(self, node):
        self._node = node

    def apply(self, spec: dict, timeout: int = 15) -> None:
        peer_n = len((spec or {}).get("peers") or [])
        timeout = wg_apply_timeout_sec(peer_n, minimum=timeout)
        logger.debug("REST wg/apply peers=%s timeout=%ss", peer_n, timeout)
        self._node.make_request("/wg/apply", timeout, spec=spec)

    def _apply_specs_direct(self, specs: list, timeout: int = 30) -> None:
        peer_n = sum(len((s or {}).get("peers") or []) for s in (specs or []))
        timeout = wg_apply_timeout_sec(peer_n, minimum=timeout)
        if len(specs) == 1:
            self.apply(specs[0], timeout=timeout)
            return
        self._node.make_request("/wg/apply-specs", timeout, specs=specs)

    def apply_specs(self, specs: list, timeout: int = 30) -> None:
        peer_n = sum(len((s or {}).get("peers") or []) for s in (specs or []))
        timeout = wg_apply_timeout_sec(peer_n, minimum=timeout)
        logger.debug("REST wg/apply-specs peers=%s specs=%s timeout=%ss", peer_n, len(specs or []), timeout)
        if peer_n > WG_APPLY_RPC_CHUNK:
            _apply_specs_chunked(
                apply_direct=self._apply_specs_direct,
                apply_batch=self.apply_batch,
                specs=list(specs or []),
                timeout=timeout,
            )
            return
        self._apply_specs_direct(list(specs or []), timeout)

    def open_udp_ports(self, ports: list, timeout: int = 15) -> int:
        try:
            res = self._node.make_request("/wg/open-udp-ports", timeout, ports=list(ports or []))
            return int((res or {}).get("opened", 0))
        except Exception:
            return 0

    def transfer(self, interface: str, timeout: int = 10) -> dict:
        res = self._node.make_request("/wg/transfer", timeout, interface=interface)
        return (res or {}).get("transfer", {})

    def apply_batch(
        self,
        *,
        interface: str,
        generation: int,
        cursor: int,
        peers: list,
        removes: list,
        timeout: int = 60,
    ) -> dict:
        return self._node.make_request(
            "/wg/apply-batch",
            timeout,
            interface=interface,
            generation=int(generation),
            cursor=int(cursor),
            peers=list(peers or []),
            removes=list(removes or []),
        ) or {}

    def sync_status(self, interface: str = "", timeout: int = 15) -> dict:
        return self._node.make_request(
            "/wg/sync-status",
            timeout,
            interface=interface or "",
        ) or {}

    def down(self, interface: str, timeout: int = 10) -> None:
        self._node.make_request("/wg/down", timeout, interface=interface)

    def apply_warp_tproxy(
        self,
        *,
        enabled: bool,
        subnets: list,
        port: int,
        interfaces: Optional[list] = None,
        timeout: int = 20,
    ) -> bool:
        res = self._node.make_request(
            "/wg/warp-tproxy",
            timeout,
            enabled=bool(enabled),
            subnets=list(subnets or []),
            port=int(port),
            interfaces=list(interfaces or []),
        )
        return bool((res or {}).get("ok"))

    def amnezia_available(self, timeout: int = 5) -> bool:
        try:
            res = self._node.make_request("/wg/amnezia-available", timeout)
            return bool((res or {}).get("available"))
        except Exception:
            return False

    def recover_awg_interface(self, interface: str, timeout: int = 10) -> bool:
        try:
            res = self._node.make_request("/wg/recover-interface", timeout, interface=interface)
            return bool((res or {}).get("recovered"))
        except Exception:
            return False

    def reconcile_awg_endpoints(self, interface: str, *, stale_sec: int = 180, timeout: int = 10) -> int:
        try:
            res = self._node.make_request(
                "/wg/reconcile-endpoints", timeout, interface=interface, stale_sec=stale_sec
            )
            return int((res or {}).get("cleared", 0))
        except Exception:
            return 0

    def flush_bad_endpoints(self, interface: str, timeout: int = 10) -> int:
        try:
            res = self._node.make_request("/wg/flush-bad-endpoints", timeout, interface=interface)
            return int((res or {}).get("cleared", 0))
        except Exception:
            return 0

    def prepare_peer_for_connect(self, interface: str, pubkey: str, timeout: int = 10) -> bool:
        try:
            res = self._node.make_request(
                "/wg/prepare-peer", timeout, interface=interface, public_key=pubkey
            )
            return bool((res or {}).get("prepared"))
        except Exception:
            return False

    def flush_stale_peers(
        self,
        interface: str,
        *,
        max_age_sec: int = 35,
        idle_sec: int = 5,
        traffic_only: bool = True,
        timeout: int = 10,
    ) -> int:
        try:
            res = self._node.make_request(
                "/wg/flush-stale-peers",
                timeout,
                interface=interface,
                max_age_sec=max_age_sec,
                idle_sec=idle_sec,
                traffic_only=traffic_only,
            )
            return int((res or {}).get("flushed", 0))
        except Exception:
            return 0

    def autoscale_create_interface(self, spec: dict, timeout: int = 30) -> None:
        self._node.make_request("/wg/autoscale/create-interface", timeout, spec=spec)

    def autoscale_hot_add_peer(
        self,
        interface: str,
        public_key: str,
        allowed_ips: str,
        *,
        preshared_key: Optional[str] = None,
        timeout: int = 15,
    ) -> None:
        self._node.make_request(
            "/wg/autoscale/hot-add",
            timeout,
            interface=interface,
            public_key=public_key,
            allowed_ips=allowed_ips,
            preshared_key=preshared_key,
        )

    def autoscale_toggle_peer(
        self,
        interface: str,
        public_key: str,
        *,
        active: bool,
        allowed_ips: str,
        preshared_key: Optional[str] = None,
        timeout: int = 15,
    ) -> None:
        self._node.make_request(
            "/wg/autoscale/toggle",
            timeout,
            interface=interface,
            public_key=public_key,
            active=active,
            allowed_ips=allowed_ips,
            preshared_key=preshared_key,
        )

    def autoscale_show_dump(self, timeout: int = 15) -> list:
        res = self._node.make_request("/wg/autoscale/dump", timeout)
        return (res or {}).get("dump", [])

    def autoscale_transfer(self, interface: str, timeout: int = 10) -> dict:
        res = self._node.make_request("/wg/autoscale/transfer", timeout, interface=interface)
        return (res or {}).get("transfer", {})


def _rpyc_obtain(value: Any) -> Any:
    """Materialize RPyC netrefs into plain Python values."""
    try:
        from rpyc.utils.classic import obtain
        return obtain(value)
    except Exception:
        return value


def _plain_tree(value: Any) -> Any:
    """Deep-copy to plain Python types (handles RPyC netrefs)."""
    value = _rpyc_obtain(value)
    if isinstance(value, dict):
        return {str(k): _plain_tree(v) for k, v in value.items()}
    if hasattr(value, "items"):
        try:
            return {str(k): _plain_tree(v) for k, v in value.items()}
        except Exception:
            return {}
    if isinstance(value, (list, tuple)):
        return [_plain_tree(v) for v in value]
    return value


class RPyCWireGuardClient(AutoScaleWireGuardMixin):
    """Talks to the node agent's exposed ``wg_*`` methods over RPyC."""

    def __init__(self, node):
        self._node = node

    def apply(self, spec: dict, timeout: int = 15) -> None:
        peer_n = len((spec or {}).get("peers") or [])
        timeout = wg_apply_timeout_sec(peer_n, minimum=timeout)
        self.apply_specs([spec], timeout=timeout)

    def _apply_specs_direct(self, specs: list, timeout: int = 30) -> None:
        peer_n = sum(len((s or {}).get("peers") or []) for s in (specs or []))
        timeout = wg_apply_timeout_sec(peer_n, minimum=timeout)
        plain_specs = [_plain_tree(s) for s in specs]
        remote = self._node.remote
        conn = getattr(self._node, "connection", None) or getattr(remote, "_conn", None)
        logger.debug(
            "RPyC wg apply peers=%s specs=%s timeout=%ss",
            peer_n,
            len(plain_specs),
            timeout,
        )
        payload = json.dumps(plain_specs, separators=(",", ":"))
        with _rpyc_sync_timeout(conn, timeout):
            try:
                if hasattr(remote, "wg_apply_specs_json"):
                    remote.wg_apply_specs_json(payload)
                elif len(plain_specs) == 1:
                    if hasattr(remote, "wg_apply_json"):
                        remote.wg_apply_json(json.dumps(plain_specs[0], separators=(",", ":")))
                    else:
                        remote.wg_apply(plain_specs[0])
                else:
                    for spec in plain_specs:
                        if hasattr(remote, "wg_apply_json"):
                            remote.wg_apply_json(json.dumps(spec, separators=(",", ":")))
                        else:
                            remote.wg_apply(spec)
            except Exception as exc:
                logger.warning(
                    "RPyC WireGuard apply failed (peers=%s timeout=%ss): %s",
                    peer_n,
                    timeout,
                    exc,
                )
                raise

    def apply_specs(self, specs: list, timeout: int = 30) -> None:
        peer_n = sum(len((s or {}).get("peers") or []) for s in (specs or []))
        timeout = wg_apply_timeout_sec(peer_n, minimum=timeout)
        plain_specs = [_plain_tree(s) for s in (specs or [])]
        # Large single-shot syncconf over RPyC fails on flaky links; stream
        # automatically so tunnel exits / reconnect heal without manual wg set.
        if peer_n > WG_APPLY_RPC_CHUNK:
            _apply_specs_chunked(
                apply_direct=self._apply_specs_direct,
                apply_batch=self.apply_batch,
                specs=plain_specs,
                timeout=timeout,
            )
            return
        self._apply_specs_direct(plain_specs, timeout)

    def open_udp_ports(self, ports: list, timeout: int = 15) -> int:
        remote = getattr(self._node, "remote", None)
        if remote is None or not hasattr(remote, "wg_open_udp_ports"):
            return 0
        try:
            return int(remote.wg_open_udp_ports(list(ports or [])) or 0)
        except Exception:
            return 0

    def transfer(self, interface: str, timeout: int = 10) -> dict:
        try:
            raw = self._node.remote.wg_transfer(interface) or {}
        except Exception:
            return {}
        if isinstance(raw, str):
            try:
                return json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return {}
        try:
            plain = _plain_tree(raw)
            return plain if isinstance(plain, dict) else {}
        except Exception:
            return {}

    def apply_batch(
        self,
        *,
        interface: str,
        generation: int,
        cursor: int,
        peers: list,
        removes: list,
        timeout: int = 60,
    ) -> dict:
        remote = self._node.remote
        conn = getattr(self._node, "connection", None) or getattr(remote, "_conn", None)
        payload = json.dumps(
            {
                "interface": interface,
                "generation": int(generation),
                "cursor": int(cursor),
                "peers": list(peers or []),
                "removes": list(removes or []),
            },
            separators=(",", ":"),
        )
        with _rpyc_sync_timeout(conn, timeout):
            if not hasattr(remote, "wg_apply_batch_json"):
                raise WireGuardTransportError("node agent has no wg_apply_batch_json")
            raw = remote.wg_apply_batch_json(payload)
        if isinstance(raw, str):
            try:
                return json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return {}
        plain = _plain_tree(raw)
        return plain if isinstance(plain, dict) else {}

    def sync_status(self, interface: str = "", timeout: int = 15) -> dict:
        remote = self._node.remote
        if not hasattr(remote, "wg_sync_status_json"):
            return {}
        raw = remote.wg_sync_status_json(interface or "")
        if isinstance(raw, str):
            try:
                return json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return {}
        plain = _plain_tree(raw)
        return plain if isinstance(plain, dict) else {}

    def down(self, interface: str, timeout: int = 10) -> None:
        self._node.remote.wg_down(interface)

    def apply_warp_tproxy(
        self,
        *,
        enabled: bool,
        subnets: list,
        port: int,
        interfaces: Optional[list] = None,
        timeout: int = 20,
    ) -> bool:
        remote = getattr(self._node, "remote", None)
        if remote is None or not hasattr(remote, "wg_warp_tproxy"):
            raise AttributeError("node agent has no wg_warp_tproxy")
        payload = {
            "enabled": bool(enabled),
            "subnets": list(subnets or []),
            "port": int(port),
            "interfaces": list(interfaces or []),
        }
        raw = remote.wg_warp_tproxy(json.dumps(payload, separators=(",", ":")))
        if isinstance(raw, str):
            try:
                raw = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                raw = {}
        plain = _plain_tree(raw) if raw else {}
        return bool((plain or {}).get("ok"))

    def amnezia_available(self, timeout: int = 5) -> bool:
        try:
            return bool(self._node.remote.wg_amnezia_available())
        except Exception:
            return False

    def recover_awg_interface(self, interface: str, timeout: int = 10) -> bool:
        try:
            if hasattr(self._node.remote, "wg_recover_awg_interface"):
                return bool(self._node.remote.wg_recover_awg_interface(interface))
        except Exception:
            pass
        return False

    def reconcile_awg_endpoints(self, interface: str, *, stale_sec: int = 180, timeout: int = 10) -> int:
        try:
            if hasattr(self._node.remote, "wg_reconcile_awg_endpoints"):
                return int(self._node.remote.wg_reconcile_awg_endpoints(interface, stale_sec))
            if hasattr(self._node.remote, "wg_flush_bad_endpoints"):
                return int(self._node.remote.wg_flush_bad_endpoints(interface))
        except Exception:
            pass
        return 0

    def flush_bad_endpoints(self, interface: str, timeout: int = 10) -> int:
        try:
            if hasattr(self._node.remote, "wg_flush_bad_endpoints"):
                return int(self._node.remote.wg_flush_bad_endpoints(interface))
        except Exception:
            pass
        return 0

    def prepare_peer_for_connect(self, interface: str, pubkey: str, timeout: int = 10) -> bool:
        try:
            if hasattr(self._node.remote, "wg_prepare_peer_for_connect"):
                return bool(self._node.remote.wg_prepare_peer_for_connect(interface, pubkey))
        except Exception:
            pass
        return False

    def flush_stale_peers(
        self,
        interface: str,
        *,
        max_age_sec: int = 35,
        idle_sec: int = 5,
        traffic_only: bool = True,
        timeout: int = 10,
    ) -> int:
        try:
            if hasattr(self._node.remote, "wg_flush_stale_peers"):
                return int(
                    self._node.remote.wg_flush_stale_peers(
                        interface, max_age_sec, idle_sec, traffic_only
                    )
                )
        except Exception:
            pass
        return 0

    def autoscale_create_interface(self, spec: dict, timeout: int = 30) -> None:
        payload = json.dumps(_plain_tree(spec), separators=(",", ":"))
        self._node.remote.wg_autoscale_create_interface_json(payload)

    def autoscale_hot_add_peer(
        self,
        interface: str,
        public_key: str,
        allowed_ips: str,
        *,
        preshared_key: Optional[str] = None,
        timeout: int = 15,
    ) -> None:
        self._node.remote.wg_autoscale_hot_add_peer(
            interface, public_key, allowed_ips, preshared_key or ""
        )

    def autoscale_toggle_peer(
        self,
        interface: str,
        public_key: str,
        *,
        active: bool,
        allowed_ips: str,
        preshared_key: Optional[str] = None,
        timeout: int = 15,
    ) -> None:
        self._node.remote.wg_autoscale_toggle_peer(
            interface, public_key, bool(active), allowed_ips, preshared_key or ""
        )

    def autoscale_show_dump(self, timeout: int = 15) -> list:
        raw = self._node.remote.wg_autoscale_show_dump_json()
        if isinstance(raw, str):
            return json.loads(raw) if raw else []
        return _plain_tree(raw)

    def autoscale_transfer(self, interface: str, timeout: int = 10) -> dict:
        raw = self._node.remote.wg_autoscale_transfer_json(interface)
        if isinstance(raw, str):
            try:
                return json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return {}
        plain = _plain_tree(raw)
        return plain if isinstance(plain, dict) else {}


def client_for_node(node) -> Optional[object]:
    """Return a WireGuard client for an already-connected node object, or
    ``None`` if the node speaks neither transport.

    Detection mirrors ``XRayNode``: ReST nodes expose ``make_request``; RPyC
    nodes expose ``remote``.

    IMPORTANT: probe the *class*, not the instance. On an RPyC node ``remote``
    is a property whose getter grabs the connection lock and calls
    ``connect()`` (with retries/sleeps). Using ``hasattr(node, "remote")`` here
    would trigger that connect on a down node — blocking the 5s usage job
    entirely (Overview freeze + "maximum number of running instances" spam).
    Checking the type never invokes the getter; the actual (bounded, timed-out)
    RPyC call happens later inside the collector's own executor.
    """
    if node is None:
        return None
    if hasattr(type(node), "make_request") or hasattr(type(node), "remote"):
        if hasattr(type(node), "make_request"):
            return RESTWireGuardClient(node)
        return RPyCWireGuardClient(node)
    return None
