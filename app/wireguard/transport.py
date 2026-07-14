"""Panel -> node transport for native WireGuard control (Phase 11.3).

Drives the node agent's ``/wg/apply`` | ``/wg/transfer`` | ``/wg/down`` over
whichever channel the node already speaks — REST (``ReSTXRayNode``) or RPyC
(``RPyCXRayNode``) — reusing the same authenticated/SSL connection the panel
holds for Xray. ``client_for_node`` auto-detects, mirroring ``XRayNode``.

The clients only depend on a tiny duck-typed surface so they are unit testable
with fakes (no live node required).
"""
import json
from typing import Any, Optional


class WireGuardTransportError(Exception):
    pass


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
        self._node.make_request("/wg/apply", timeout, spec=spec)

    def apply_specs(self, specs: list, timeout: int = 30) -> None:
        if len(specs) == 1:
            self.apply(specs[0], timeout=timeout)
            return
        self._node.make_request("/wg/apply-specs", timeout, specs=specs)

    def transfer(self, interface: str, timeout: int = 10) -> dict:
        res = self._node.make_request("/wg/transfer", timeout, interface=interface)
        return (res or {}).get("transfer", {})

    def down(self, interface: str, timeout: int = 10) -> None:
        self._node.make_request("/wg/down", timeout, interface=interface)

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
        self.apply_specs([spec], timeout=timeout)

    def apply_specs(self, specs: list, timeout: int = 30) -> None:
        plain_specs = [_plain_tree(s) for s in specs]
        remote = self._node.remote
        payload = json.dumps(plain_specs, separators=(",", ":"))
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

    def down(self, interface: str, timeout: int = 10) -> None:
        self._node.remote.wg_down(interface)

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
