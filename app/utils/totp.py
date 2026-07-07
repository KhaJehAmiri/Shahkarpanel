"""Dependency-free TOTP (RFC 6238) for optional admin 2FA.

Compatible with Google Authenticator, Authy, Aegis, 1Password, etc. Uses the
Python standard library only (no extra dependency), SHA1 / 6 digits / 30s step
which is the de-facto authenticator standard.
"""
import base64
import hashlib
import hmac
import os
import struct
import time
import urllib.parse

DIGITS = 6
PERIOD = 30


def generate_secret(length: int = 20) -> str:
    """Return a new random base32 secret (no padding)."""
    return base64.b32encode(os.urandom(length)).decode("ascii").rstrip("=")


def _hotp(secret: str, counter: int, digits: int = DIGITS) -> str:
    # Restore base32 padding before decoding.
    padded = secret.strip().replace(" ", "").upper()
    padded += "=" * (-len(padded) % 8)
    key = base64.b32decode(padded, casefold=True)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10 ** digits)).zfill(digits)


def verify(secret: str, code: str, window: int = 1) -> bool:
    """Validate ``code`` against ``secret`` allowing +/- ``window`` steps of clock skew."""
    if not secret or not code:
        return False
    code = code.strip().replace(" ", "")
    if not code.isdigit():
        return False
    code = code.zfill(DIGITS)
    counter = int(time.time()) // PERIOD
    for drift in range(-window, window + 1):
        if hmac.compare_digest(_hotp(secret, counter + drift), code):
            return True
    return False


def provisioning_uri(secret: str, account_name: str, issuer: str = "NexusPanel") -> str:
    """Build an otpauth:// URI for QR-code enrollment."""
    label = urllib.parse.quote(f"{issuer}:{account_name}")
    params = urllib.parse.urlencode(
        {
            "secret": secret,
            "issuer": issuer,
            "digits": DIGITS,
            "period": PERIOD,
            "algorithm": "SHA1",
        }
    )
    return f"otpauth://totp/{label}?{params}"
