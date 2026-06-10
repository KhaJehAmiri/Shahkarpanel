"""Read a PEM certificate from disk and return metadata for the panel."""
import os
from datetime import datetime, timezone
from typing import Any, Dict


_PUBLIC_CA_MARKERS = (
    "let's encrypt",
    "lets encrypt",
    "letsencrypt",
)


def inspect_cert_file(path: str) -> Dict[str, Any]:
    if not path or not os.path.isfile(path):
        return {"present": False, "trusted": False, "issuer": None, "expires_at": None}
    try:
        from cryptography import x509
        from cryptography.hazmat.backends import default_backend

        with open(path, "rb") as fh:
            cert = x509.load_pem_x509_certificate(fh.read(), default_backend())
        issuer = cert.issuer.rfc4514_string()
        subject = cert.subject.rfc4514_string()
        expires = cert.not_valid_after_utc.replace(tzinfo=timezone.utc)
        low = issuer.lower()
        public = any(m in low for m in _PUBLIC_CA_MARKERS) and issuer != subject
        return {
            "present": True,
            "issuer": issuer,
            "subject": subject,
            "expires_at": expires.isoformat(),
            "trusted": public,
            "self_signed": issuer == subject,
        }
    except Exception as exc:
        return {"present": False, "trusted": False, "error": str(exc)}
