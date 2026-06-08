"""Panel -> node transport for sing-box control (Hysteria2 / TUIC).

Drives the node agent's ``/singbox/apply`` | ``/singbox/transfer`` |
``/singbox/down`` over whichever channel the node speaks — REST or RPyC —
reusing the same authenticated connection the panel holds for Xray. Mirrors
``app.wireguard.transport``; clients depend on a tiny duck-typed surface so
they stay unit testable with fakes.
"""
import json
from typing import Any, Optional


class RESTSingBoxClient:
    """Talks to the node agent's ``/singbox/*`` REST routes via a ReST node's
    ``make_request`` (which injects ``session_id`` + client-cert auth)."""

    def __init__(self, node):
        self._node = node

    def apply(self, spec: dict, timeout: int = 15) -> None:
        self._node.make_request("/singbox/apply", timeout, spec=spec)

    def transfer(self, timeout: int = 10) -> dict:
        res = self._node.make_request("/singbox/transfer", timeout)
        return (res or {}).get("transfer", {})

    def down(self, timeout: int = 10) -> None:
        self._node.make_request("/singbox/down", timeout)


def _rpyc_obtain(value: Any) -> Any:
    try:
        from rpyc.utils.classic import obtain
        return obtain(value)
    except Exception:
        return value


def _plain_tree(value: Any) -> Any:
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


class RPyCSingBoxClient:
    """Talks to the node agent's exposed ``singbox_*`` methods over RPyC."""

    def __init__(self, node):
        self._node = node

    def apply(self, spec: dict, timeout: int = 15) -> None:
        plain = _plain_tree(spec)
        self._node.remote.singbox_apply_json(json.dumps(plain, separators=(",", ":")))

    def transfer(self, timeout: int = 10) -> dict:
        try:
            raw = self._node.remote.singbox_transfer() or {}
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

    def down(self, timeout: int = 10) -> None:
        self._node.remote.singbox_down()


def client_for_node(node) -> Optional[object]:
    """Return a sing-box client for an already-connected node object, or
    ``None`` if the node speaks neither transport."""
    if node is None:
        return None
    if hasattr(node, "make_request"):
        return RESTSingBoxClient(node)
    if hasattr(node, "remote"):
        return RPyCSingBoxClient(node)
    return None
