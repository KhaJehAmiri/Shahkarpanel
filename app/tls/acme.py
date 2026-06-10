"""Let's Encrypt issuance on remote nodes over SSH (certbot + cron renew).

Supports both DNS domain names and public IP addresses (LE short-lived IP certs).
"""
import ipaddress
import shlex
from typing import Literal, Optional, Tuple

from app.provisioning import ProvisioningError, SSHCredentials, run_remote_command

DEFAULT_TLS_DIR = "/var/lib/nexuspanel-node/tls"
DEFAULT_CERT = f"{DEFAULT_TLS_DIR}/cert.pem"
DEFAULT_KEY = f"{DEFAULT_TLS_DIR}/key.pem"

TlsKind = Literal["domain", "ip"]


def _looks_like_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip())
        return True
    except ValueError:
        return False


def normalize_tls_target(value: str, kind: str = "auto") -> Tuple[str, TlsKind]:
    """Return (identifier, kind) for certbot -d and live directory naming."""
    raw = value.strip()
    if not raw:
        raise ProvisioningError("A domain name or public IP is required for Let's Encrypt")

    if kind == "auto":
        kind = "ip" if _looks_like_ip(raw) else "domain"
    elif kind not in ("domain", "ip"):
        raise ProvisioningError("tls_kind must be domain, ip, or auto")

    if kind == "ip":
        try:
            identifier = str(ipaddress.ip_address(raw))
        except ValueError as exc:
            raise ProvisioningError("A valid public IP address is required") from exc
    else:
        identifier = raw.lower()
        if "@" in identifier or _looks_like_ip(identifier):
            raise ProvisioningError("A valid DNS domain is required for domain-mode LE")

    return identifier, kind


def build_issue_command(
    target: str,
    email: str,
    *,
    tls_kind: str = "auto",
    tls_dir: str = DEFAULT_TLS_DIR,
    cert_path: str = DEFAULT_CERT,
    key_path: str = DEFAULT_KEY,
) -> str:
    """Shell script run on the node host to obtain and install a LE cert."""
    identifier, kind = normalize_tls_target(target, tls_kind)
    email = email.strip()
    if not email or "@" not in email:
        raise ProvisioningError("A contact email is required for Let's Encrypt")

    q = shlex.quote
    le_dir = f"/etc/letsencrypt/live/{identifier}"
    cron_line = (
        f"0 3 * * * root certbot renew --quiet --deploy-hook "
        f"\"cp {le_dir}/fullchain.pem {cert_path} && "
        f"cp {le_dir}/privkey.pem {key_path} && "
        f"docker restart nexusnode >/dev/null 2>&1 || true\" "
        f">> /var/log/nexuspanel-le-renew.log 2>&1"
    )
    # IP certs are short-lived (~6 days); cron renew handles both kinds.
    return (
        "set -e; "
        f"TARGET={q(identifier)}; EMAIL={q(email)}; KIND={q(kind)}; "
        f"TLS_DIR={q(tls_dir)}; CERT={q(cert_path)}; KEY={q(key_path)}; "
        "mkdir -p \"$TLS_DIR\"; "
        "if ! command -v certbot >/dev/null 2>&1; then "
        "  (apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq certbot) "
        "  || (yum install -y certbot 2>/dev/null) "
        "  || (dnf install -y certbot 2>/dev/null) "
        "  || pip3 install --break-system-packages certbot 2>/dev/null "
        "  || pip3 install certbot; "
        "fi; "
        "certbot certonly --standalone --preferred-challenges http "
        "--non-interactive --agree-tos --no-eff-email "
        f"-m \"$EMAIL\" -d \"$TARGET\"; "
        f"cp \"{le_dir}/fullchain.pem\" \"$CERT\"; "
        f"cp \"{le_dir}/privkey.pem\" \"$KEY\"; "
        "chmod 644 \"$CERT\"; chmod 600 \"$KEY\"; "
        f"grep -q nexuspanel-le-renew /etc/crontab 2>/dev/null || echo {q(cron_line)} >> /etc/crontab; "
        "docker restart nexusnode >/dev/null 2>&1 || true; "
        "echo ISSUED"
    )


def build_renew_command(
    target: str,
    *,
    tls_kind: str = "auto",
    cert_path: str = DEFAULT_CERT,
    key_path: str = DEFAULT_KEY,
) -> str:
    identifier, _ = normalize_tls_target(target, tls_kind)
    q = shlex.quote
    le_dir = f"/etc/letsencrypt/live/{identifier}"
    return (
        "set -e; "
        f"TARGET={q(identifier)}; CERT={q(cert_path)}; KEY={q(key_path)}; "
        "certbot renew --quiet; "
        f"cp \"{le_dir}/fullchain.pem\" \"$CERT\"; "
        f"cp \"{le_dir}/privkey.pem\" \"$KEY\"; "
        "docker restart nexusnode >/dev/null 2>&1 || true; "
        "echo RENEWED"
    )


def issue_certificate(
    creds: SSHCredentials,
    target: str,
    email: str,
    *,
    tls_kind: str = "auto",
    cert_path: str = DEFAULT_CERT,
    key_path: str = DEFAULT_KEY,
) -> str:
    """SSH to the node host, run certbot, return remote stdout."""
    cmd = build_issue_command(
        target, email, tls_kind=tls_kind, cert_path=cert_path, key_path=key_path,
    )
    return run_remote_command(creds, cmd, exec_timeout=900)


def renew_certificate(
    creds: SSHCredentials,
    target: str,
    *,
    tls_kind: str = "auto",
    cert_path: str = DEFAULT_CERT,
    key_path: str = DEFAULT_KEY,
) -> str:
    cmd = build_renew_command(target, tls_kind=tls_kind, cert_path=cert_path, key_path=key_path)
    return run_remote_command(creds, cmd, exec_timeout=600)
