"""Panel -> node transport for sing-box control (Hysteria2 / TUIC).

Drives the node agent's ``/singbox/apply`` | ``/singbox/transfer`` |
``/singbox/down`` | ``/singbox/revoke`` over whichever channel the node
speaks — REST or RPyC — reusing the same authenticated connection the
panel holds for Xray. Mirrors ``app.wireguard.transport``; clients depend
on a tiny duck-typed surface so they stay unit testable with fakes.
"""
import base64
import gzip
import json
from typing import Any, Optional


def _with_sync_timeout(node, timeout, fn):
    """Temporarily raise RPyC ``sync_request_timeout`` for a large apply."""
    conn = getattr(node, "connection", None)
    cfg = getattr(conn, "_config", None) if conn is not None else None
    prev = None
    bumped = isinstance(cfg, dict) and timeout
    if bumped:
        prev = cfg.get("sync_request_timeout")
        cfg["sync_request_timeout"] = timeout
    try:
        return fn()
    finally:
        if bumped and isinstance(cfg, dict):
            cfg["sync_request_timeout"] = prev


class RESTSingBoxClient:
    """Talks to the node agent's ``/singbox/*`` REST routes via a ReST node's
    ``make_request`` (which injects ``session_id`` + client-cert auth)."""

    def __init__(self, node):
        self._node = node

    def apply(self, spec: dict, timeout: int = 60) -> None:
        self._node.make_request("/singbox/apply", timeout, spec=spec)

    def transfer(self, timeout: int = 10) -> dict:
        res = self._node.make_request("/singbox/transfer", timeout)
        return (res or {}).get("transfer", {})

    def revoke(self, names, timeout: int = 15) -> dict:
        res = self._node.make_request("/singbox/revoke", timeout, names=list(names or []))
        return res if isinstance(res, dict) else {}

    def unrevoke(self, names, timeout: int = 15) -> dict:
        res = self._node.make_request("/singbox/unrevoke", timeout, names=list(names or []))
        return res if isinstance(res, dict) else {}

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

    def apply(self, spec: dict, timeout: int = 60) -> None:
        plain = _plain_tree(spec)
        raw = json.dumps(plain, separators=(",", ":")).encode()
        gz = base64.b64encode(gzip.compress(raw, compresslevel=6)).decode("ascii")

        def _call():
            remote = self._node.remote
            try:
                return remote.singbox_apply_gz(gz)
            except AttributeError:
                return remote.singbox_apply_json(raw.decode())

        _with_sync_timeout(self._node, timeout, _call)

    def transfer(self, timeout: int = 10) -> dict:
        # Never dial from the usage tick — a dead channel returns empty and
        # the health checker reconnects. Dialling here used to spawn one
        # ThreadPool worker per node per tick that then sat forever on
        # ``node.remote`` → ``connect()``.
        try_remote = getattr(self._node, "try_remote", None)
        if callable(try_remote):
            remote = try_remote()
            if remote is None:
                return {}
        else:
            # Fakes / REST-shaped objects expose ``remote`` as a plain attr.
            remote = getattr(self._node, "remote", None)
            if remote is None:
                return {}
        try:
            raw = remote.singbox_transfer() or {}
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

    def revoke(self, names, timeout: int = 15) -> dict:
        try_remote = getattr(self._node, "try_remote", None)
        if callable(try_remote):
            remote = try_remote()
            if remote is None:
                return {}
        else:
            remote = getattr(self._node, "remote", None)
            if remote is None:
                return {}
        payload = json.dumps(list(names or []), separators=(",", ":"))
        try:
            raw = remote.singbox_revoke_json(payload)
        except AttributeError:
            return {}
        except Exception:
            return {}
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        plain = _plain_tree(raw)
        return plain if isinstance(plain, dict) else {}

    def unrevoke(self, names, timeout: int = 15) -> dict:
        try_remote = getattr(self._node, "try_remote", None)
        if callable(try_remote):
            remote = try_remote()
            if remote is None:
                return {}
        else:
            remote = getattr(self._node, "remote", None)
            if remote is None:
                return {}
        payload = json.dumps(list(names or []), separators=(",", ":"))
        try:
            raw = remote.singbox_unrevoke_json(payload)
        except AttributeError:
            return {}
        except Exception:
            return {}
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        plain = _plain_tree(raw)
        return plain if isinstance(plain, dict) else {}

    def down(self, timeout: int = 10) -> None:
        self._node.remote.singbox_down()


def client_for_node(node) -> Optional[object]:
    """Return a sing-box client for an already-connected node object, or
    ``None`` if the node speaks neither transport.

    Probe the *class*, not the instance: on an RPyC node ``remote`` is a
    property whose getter takes the connection lock and calls ``connect()``,
    so asking an unreachable node whether it *has* the attribute dials it and
    blocks the caller for the whole connect. Mirrors
    ``app.wireguard.transport.client_for_node``.
    """
    if node is None:
        return None
    if _declares(node, "make_request"):
        return RESTSingBoxClient(node)
    if _declares(node, "remote"):
        return RPyCSingBoxClient(node)
    return None


def _declares(node, name: str) -> bool:
    """Attribute presence without running a property getter."""
    return hasattr(type(node), name) or name in getattr(node, "__dict__", {})
