"""TLS inspection and Let's Encrypt command builder."""
from datetime import datetime, timezone

from app.tls.acme import (
    build_issue_command,
    build_renew_command,
    normalize_tls_target,
)
from app.tls.inspect import cert_requires_insecure, inspect_pem, is_public_ca_issuer
from app.tls.self_signed import build_self_signed_command


def _self_signed_pem() -> str:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc))
        .not_valid_after(datetime.now(timezone.utc).replace(year=2030))
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def test_is_public_ca_issuer_detects_le():
    assert is_public_ca_issuer("CN=Let's Encrypt Authority X3")
    assert not is_public_ca_issuer("CN=test")


def test_inspect_pem_self_signed():
    meta = inspect_pem(_self_signed_pem())
    assert meta["self_signed"] is True
    assert meta["trusted"] is False


def test_cert_requires_insecure_rules():
    assert cert_requires_insecure(tls_trusted=True, sni="vpn.example.com") is False
    assert cert_requires_insecure(tls_trusted=False, sni="178.83.45.253") is True
    assert cert_requires_insecure(tls_trusted=None, sni="vpn.example.com") is True


def test_build_issue_command_contains_domain():
    cmd = build_issue_command("vpn.example.com", "ops@example.com")
    assert "vpn.example.com" in cmd
    assert "certbot" in cmd
    assert "ISSUED" in cmd


def test_build_issue_command_supports_ip():
    cmd = build_issue_command("178.83.45.253", "ops@example.com", tls_kind="ip")
    assert "178.83.45.253" in cmd
    assert "certbot" in cmd
    identifier, kind = normalize_tls_target("178.83.45.253", "ip")
    assert identifier == "178.83.45.253"
    assert kind == "ip"


def test_normalize_tls_target_auto_detects():
    identifier, kind = normalize_tls_target("vpn.example.com")
    assert identifier == "vpn.example.com"
    assert kind == "domain"
    identifier, kind = normalize_tls_target("91.220.8.251")
    assert identifier == "91.220.8.251"
    assert kind == "ip"


def test_build_renew_command():
    cmd = build_renew_command("vpn.example.com")
    assert "certbot renew" in cmd
    cmd_ip = build_renew_command("178.83.45.253", tls_kind="ip")
    assert "178.83.45.253" in cmd_ip


def test_build_self_signed_command():
    cmd = build_self_signed_command("node.example.com")
    assert "openssl" in cmd
    assert "SELF_SIGNED" in cmd
