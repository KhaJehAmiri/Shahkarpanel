"""Protocol backend registry."""
from typing import Dict, List, Optional

from .backends import (
    AnyTLSBackend,
    Hysteria2Backend,
    SingBoxBackend,
    TuicBackend,
    XrayBackend,
)
from .base import ProtocolBackend

_registry: Dict[str, ProtocolBackend] = {}


def register(backend: ProtocolBackend) -> None:
    _registry[backend.name] = backend


def get_backend(name: str) -> Optional[ProtocolBackend]:
    return _registry.get(name)


def all_backends() -> List[ProtocolBackend]:
    return list(_registry.values())


def available_backends() -> List[ProtocolBackend]:
    return [b for b in _registry.values() if b.available]


def backend_for_protocol(protocol: str) -> Optional[ProtocolBackend]:
    """Return the first *available* backend that serves ``protocol``."""
    for backend in _registry.values():
        if backend.available and backend.supports(protocol):
            return backend
    return None


# Register built-in backends. Xray is the live engine; the rest are descriptors.
for _backend in (XrayBackend(), SingBoxBackend(), Hysteria2Backend(), TuicBackend(), AnyTLSBackend()):
    register(_backend)


__all__ = [
    "ProtocolBackend",
    "register",
    "get_backend",
    "all_backends",
    "available_backends",
    "backend_for_protocol",
]
