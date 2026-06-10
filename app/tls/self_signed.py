"""Bootstrap self-signed TLS on remote nodes when LE is skipped."""
import shlex

from app.provisioning import SSHCredentials, run_remote_command
from app.tls.acme import DEFAULT_CERT, DEFAULT_KEY


def build_self_signed_command(
    sni: str,
    *,
    cert_path: str = DEFAULT_CERT,
    key_path: str = DEFAULT_KEY,
    days: int = 365,
) -> str:
    """Generate a local self-signed cert on the node host (openssl)."""
    sni = sni.strip() or "localhost"
    q = shlex.quote
    return (
        "set -e; "
        f"SNI={q(sni)}; CERT={q(cert_path)}; KEY={q(key_path)}; "
        "TLS_DIR=$(dirname \"$CERT\"); mkdir -p \"$TLS_DIR\"; "
        "if ! command -v openssl >/dev/null 2>&1; then "
        "  (apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq openssl) "
        "  || (yum install -y openssl 2>/dev/null) "
        "  || (dnf install -y openssl 2>/dev/null); "
        "fi; "
        "openssl req -x509 -nodes -newkey rsa:2048 "
        f"-keyout \"$KEY\" -out \"$CERT\" -days {int(days)} "
        "-subj \"/CN=$SNI\"; "
        "chmod 644 \"$CERT\"; chmod 600 \"$KEY\"; "
        "docker restart nexusnode >/dev/null 2>&1 || true; "
        "echo SELF_SIGNED"
    )


def install_self_signed(
    creds: SSHCredentials,
    sni: str,
    *,
    cert_path: str = DEFAULT_CERT,
    key_path: str = DEFAULT_KEY,
) -> str:
    cmd = build_self_signed_command(sni, cert_path=cert_path, key_path=key_path)
    return run_remote_command(creds, cmd, exec_timeout=120)
