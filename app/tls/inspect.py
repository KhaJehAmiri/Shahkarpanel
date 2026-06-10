"""Parse PEM certificates and decide whether clients must skip TLS verify."""
from datetime import datetime, timezone
from typing import Any, Dict, Optional

_PUBLIC_CA_MARKERS = (
    "let's encrypt",
    "lets encrypt",
    "letsencrypt",
    "digicert",
    "google trust",
    "cloudflare inc",
    "zerossl",
)


def is_public_ca_issuer(issuer: str) -> bool:
    low = (issuer or "").lower()
    return any(m in low for m in _PUBLIC_CA_MARKERS)


def _looks_like_ip(host: Optional[str]) -> bool:
    if not host:
        return False
    host = host.strip()
    if host.count(".") == 3 and all(p.isdigit() for p in host.split(".")):
        return True
    if ":" in host:
        return True
    return False


def inspect_pem(cert_pem: str) -> Dict[str, Any]:
    """Return issuer, expiry, and whether the cert chains to a public CA."""
    from cryptography import x509
    from cryptography.hazmat.backends import default_backend

    cert = x509.load_pem_x509_certificate(cert_pem.encode("utf-8"), default_backend())
    issuer = cert.issuer.rfc4514_string()
    subject = cert.subject.rfc4514_string()
    expires = cert.not_valid_after_utc.replace(tzinfo=timezone.utc)
    self_signed = issuer == subject
    public = is_public_ca_issuer(issuer) and not self_signed
    return {
        "issuer": issuer,
        "subject": subject,
        "expires_at": expires.isoformat(),
        "self_signed": self_signed,
        "public_ca": public,
        "trusted": public,
    }


def cert_requires_insecure(
    *,
    tls_trusted: Optional[bool] = None,
    sni: Optional[str] = None,
) -> bool:
    """Whether QUIC share links should carry ``insecure=1``."""
    if tls_trusted is True:
        return False
    if _looks_like_ip(sni):
        return True
    return tls_trusted is not True


def days_until_expiry(expires_at: Optional[datetime]) -> Optional[int]:
    if expires_at is None:
        return None
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    delta = expires_at - datetime.now(timezone.utc)
    return max(0, delta.days)
