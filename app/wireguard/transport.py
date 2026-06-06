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


class RESTWireGuardClient:
    """Talks to the node agent's ``/wg/*`` REST routes via a ReST node's
    ``make_request`` (which injects ``session_id`` and client-cert auth)."""

    def __init__(self, node):
        self._node = node

    def apply(self, spec: dict, timeout: int = 15) -> None:
        self._node.make_request("/wg/apply", timeout, spec=spec)

    def transfer(self, interface: str, timeout: int = 10) -> dict:
        res = self._node.make_request("/wg/transfer", timeout, interface=interface)
        return (res or {}).get("transfer", {})

    def down(self, interface: str, timeout: int = 10) -> None:
        self._node.make_request("/wg/down", timeout, interface=interface)


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


class RPyCWireGuardClient:
    """Talks to the node agent's exposed ``wg_*`` methods over RPyC."""

    def __init__(self, node):
        self._node = node

    def apply(self, spec: dict, timeout: int = 15) -> None:
        # Ship JSON text — RPyC netrefs break dict.get() inside the node agent.
        plain = _plain_tree(spec)
        remote = self._node.remote
        if hasattr(remote, "wg_apply_json"):
            remote.wg_apply_json(json.dumps(plain, separators=(",", ":")))
        else:
            remote.wg_apply(plain)

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


def client_for_node(node) -> Optional[object]:
    """Return a WireGuard client for an already-connected node object, or
    ``None`` if the node speaks neither transport.

    Detection mirrors ``XRayNode``: ReST nodes expose ``make_request``; RPyC
    nodes expose ``remote``.
    """
    if node is None:
        return None
    if hasattr(node, "make_request"):
        return RESTWireGuardClient(node)
    if hasattr(node, "remote"):
        return RPyCWireGuardClient(node)
    return None
