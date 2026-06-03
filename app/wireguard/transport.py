"""Panel -> node transport for native WireGuard control (Phase 11.3).

Drives the node agent's ``/wg/apply`` | ``/wg/transfer`` | ``/wg/down`` over
whichever channel the node already speaks — REST (``ReSTXRayNode``) or RPyC
(``RPyCXRayNode``) — reusing the same authenticated/SSL connection the panel
holds for Xray. ``client_for_node`` auto-detects, mirroring ``XRayNode``.

The clients only depend on a tiny duck-typed surface so they are unit testable
with fakes (no live node required).
"""
from typing import Optional


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


class RPyCWireGuardClient:
    """Talks to the node agent's exposed ``wg_*`` methods over RPyC."""

    def __init__(self, node):
        self._node = node

    def apply(self, spec: dict, timeout: int = 15) -> None:
        self._node.remote.wg_apply(spec)

    def transfer(self, interface: str, timeout: int = 10) -> dict:
        # rpyc returns a netref; coerce to a plain dict for the panel side.
        return dict(self._node.remote.wg_transfer(interface) or {})

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
