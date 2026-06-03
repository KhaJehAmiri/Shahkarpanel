"""WireGuard key helpers.

WireGuard uses Curve25519 (X25519) keys encoded as base64 of 32 raw bytes —
identical to what ``wg genkey`` / ``wg pubkey`` produce — so the generated
material is interoperable with stock WireGuard clients and the node interface.
"""
import base64
import os

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)


def generate_keypair() -> tuple:
    """Return ``(private_key, public_key)`` as base64 strings."""
    private = X25519PrivateKey.generate()
    private_bytes = private.private_bytes(
        Encoding.Raw, PrivateFormat.Raw, NoEncryption()
    )
    public_bytes = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return (
        base64.b64encode(private_bytes).decode(),
        base64.b64encode(public_bytes).decode(),
    )


def public_key_from_private(private_key_b64: str) -> str:
    """Derive the base64 public key from a base64 WireGuard private key."""
    raw = base64.b64decode(private_key_b64)
    private = X25519PrivateKey.from_private_bytes(raw)
    public_bytes = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(public_bytes).decode()


def generate_preshared_key() -> str:
    """Return a fresh base64 32-byte preshared key (optional WG hardening)."""
    return base64.b64encode(os.urandom(32)).decode()
