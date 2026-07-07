"""TLS fields for subscription / client export (SNI, ECH, cert pin)."""
from __future__ import annotations

import hashlib
import ipaddress
import secrets
from typing import Any

from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.serialization import Encoding


def is_ip_literal(value: str) -> bool:
    host = str(value or "").strip().split("/", 1)[0]
    if not host:
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _domain_from_address(address: str) -> str | None:
    addr = str(address or "").strip()
    if not addr or is_ip_literal(addr):
        return None
    return addr.split(":", 1)[0]


def cert_pin_sha256(cert_pem: bytes) -> str | None:
    if not cert_pem:
        return None
    try:
        cert = x509.load_pem_x509_certificate(cert_pem, default_backend())
        digest = hashlib.sha256(cert.public_bytes(Encoding.DER)).hexdigest()
        return digest.lower()
    except Exception:
        return None


def cert_is_self_signed(cert_pem: bytes) -> bool:
    try:
        cert = x509.load_pem_x509_certificate(cert_pem, default_backend())
        return cert.issuer == cert.subject
    except Exception:
        return False


def read_first_cert_pem(tls_settings: dict | None) -> bytes | None:
    if not isinstance(tls_settings, dict):
        return None
    for certificate in tls_settings.get("certificates") or []:
        if not isinstance(certificate, dict):
            continue
        path = certificate.get("certificateFile")
        if path:
            try:
                with open(path, "rb") as f:
                    return f.read()
            except OSError:
                continue
        inline = certificate.get("certificate")
        if inline:
            if isinstance(inline, list):
                inline = "\n".join(str(x) for x in inline if x)
            if isinstance(inline, str):
                return inline.encode()
    return None


def analyze_inbound_tls(tls_settings: dict | None) -> dict[str, Any]:
    """Extract subscription-relevant TLS metadata from inbound tlsSettings."""
    out: dict[str, Any] = {
        "tls_server_name": "",
        "cert_sans": [],
        "cert_pin_sha256": None,
        "cert_self_signed": False,
        "ech_config_list": None,
    }
    if not isinstance(tls_settings, dict):
        return out

    out["tls_server_name"] = str(tls_settings.get("serverName") or "").strip()

    ech = tls_settings.get("echConfigList")
    if ech:
        if isinstance(ech, list):
            ech = next((str(x).strip() for x in ech if str(x).strip()), "")
        else:
            ech = str(ech).strip()
        if ech:
            out["ech_config_list"] = ech

    cert_pem = read_first_cert_pem(tls_settings)
    if cert_pem:
        out["cert_pin_sha256"] = cert_pin_sha256(cert_pem)
        out["cert_self_signed"] = cert_is_self_signed(cert_pem)
        try:
            from app.utils.crypto import get_cert_SANs

            out["cert_sans"] = [str(s) for s in get_cert_SANs(cert_pem)]
        except Exception:
            out["cert_sans"] = []

    return out


def is_tls_fronted(host_port: int | None, inbound_port: int | None) -> bool:
    """True when the client connects to a different port than Xray listens on."""
    if host_port is None or inbound_port is None:
        return False
    try:
        return int(host_port) != int(inbound_port)
    except (TypeError, ValueError):
        return False


def _sni_candidates(raw: Any) -> list[str]:
    """Normalize inbound SNI metadata (list, str, or empty) for client export."""
    if raw is None:
        return []
    if isinstance(raw, str):
        text = raw.strip()
        return [text] if text else []
    if isinstance(raw, (list, tuple)):
        out: list[str] = []
        for item in raw:
            text = str(item or "").strip()
            if text:
                out.append(text)
        return out
    text = str(raw).strip()
    return [text] if text else []


def _sni_matches_cert(sni: str, cert_sans: list[str]) -> bool:
    if not sni:
        return False
    return sni in cert_sans


def _pick_direct_sni(
    *,
    tls_server_name: str,
    cert_sans: list[str],
    inbound_sni_candidates: list[str],
) -> str:
    """Pick SNI that the Xray listener certificate actually covers."""
    domains = [s for s in cert_sans if s and not is_ip_literal(s)]
    ips = [s for s in cert_sans if s and is_ip_literal(s)]

    if tls_server_name and _sni_matches_cert(tls_server_name, cert_sans):
        return tls_server_name

    if tls_server_name and not _sni_matches_cert(tls_server_name, cert_sans):
        if domains:
            return domains[0]
        if ips:
            return ips[0]

    for candidate in inbound_sni_candidates:
        c = str(candidate).strip()
        if not c or "*" in c:
            continue
        if _sni_matches_cert(c, cert_sans):
            return c.replace("*", secrets.token_hex(8)) if "*" in c else c

    if domains:
        return domains[0]
    if ips:
        return ips[0]
    if tls_server_name:
        return tls_server_name
    if inbound_sni_candidates:
        raw = str(inbound_sni_candidates[0]).strip()
        return raw.replace("*", secrets.token_hex(8)) if "*" in raw else raw
    return ""


def _pick_fronted_sni(
    *,
    host_address: str,
    host_sni_override: str,
    tls_server_name: str,
    inbound_sni_candidates: list[str],
) -> str:
    if host_sni_override:
        return host_sni_override
    domain = _domain_from_address(host_address)
    if domain:
        return domain
    if tls_server_name:
        return tls_server_name
    for candidate in inbound_sni_candidates:
        c = str(candidate).strip()
        if c and not is_ip_literal(c):
            return c.replace("*", secrets.token_hex(8)) if "*" in c else c
    return tls_server_name or (str(inbound_sni_candidates[0]).strip() if inbound_sni_candidates else "")


def resolve_subscription_tls(
    *,
    inbound_meta: dict,
    host_address: str,
    host_port: int | None,
    inbound_port: int | None,
    host_sni_override: str = "",
    host_tls: str | None = None,
) -> dict[str, Any]:
    """Compute client-facing TLS fields aligned with the real connection path."""
    tls_server_name = str(inbound_meta.get("tls_server_name") or "").strip()
    cert_sans = list(inbound_meta.get("cert_sans") or [])
    cert_pin = inbound_meta.get("cert_pin_sha256")
    cert_self_signed = bool(inbound_meta.get("cert_self_signed"))
    ech = inbound_meta.get("ech_config_list")
    candidates = _sni_candidates(inbound_meta.get("sni"))
    fronted = is_tls_fronted(host_port, inbound_port)
    inbound_tls = str(inbound_meta.get("tls") or "none")

    if fronted:
        sni = _pick_fronted_sni(
            host_address=host_address,
            host_sni_override=host_sni_override,
            tls_server_name=tls_server_name,
            inbound_sni_candidates=candidates,
        )
        if host_tls == "none":
            client_tls = "none"
        elif host_tls == "tls":
            client_tls = "tls"
        elif host_tls == "reality":
            client_tls = "reality"
        else:
            # inbound_default / same — inherit inbound security
            client_tls = inbound_tls if inbound_tls != "none" else ("tls" if fronted else "none")
        return {
            "sni": sni,
            "ech_config_list": None,
            "cert_pin_sha256": None,
            "tls_fronted": True,
            "client_tls": client_tls,
        }

    sni = _pick_direct_sni(
        tls_server_name=tls_server_name,
        cert_sans=cert_sans,
        inbound_sni_candidates=candidates,
    )
    use_pin = None
    if cert_pin and (
        cert_self_signed
        or (tls_server_name and not _sni_matches_cert(tls_server_name, cert_sans))
    ):
        use_pin = cert_pin

    return {
        "sni": sni,
        "ech_config_list": ech,
        "cert_pin_sha256": use_pin,
        "tls_fronted": False,
        "client_tls": str(inbound_meta.get("tls") or "none"),
    }
