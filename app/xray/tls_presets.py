"""Discover TLS certificate paths and generate self-signed certs for Xray inbounds."""
from __future__ import annotations

import glob
import ipaddress
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from config import XRAY_EXECUTABLE_PATH

XRAY_TLS_DIR = Path("/var/lib/shahkar/xray-tls")


def _ensure_tls_dir() -> None:
    """Ensure TLS output directory exists and is writable by the panel user."""
    try:
        XRAY_TLS_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as err:
        raise RuntimeError(f"Cannot create TLS directory {XRAY_TLS_DIR}: {err}") from err
    if not os.access(XRAY_TLS_DIR, os.W_OK):
        raise RuntimeError(
            f"TLS directory is not writable: {XRAY_TLS_DIR}. "
            "Run on the host: chown -R 1000:1000 /var/lib/shahkar/xray-tls"
        )


def _remove_if_writable(path: Path) -> None:
    if not path.is_file():
        return
    try:
        path.unlink()
    except PermissionError as err:
        raise RuntimeError(
            f"Cannot overwrite {path}: permission denied. "
            "Run on the host: chown -R 1000:1000 /var/lib/shahkar/xray-tls"
        ) from err


def _readable(path: str) -> bool:
    try:
        return os.path.isfile(path) and os.access(path, os.R_OK)
    except OSError:
        return False


def _host_from_server_name(raw: str) -> str:
    """Strip optional :port from a server name / SNI."""
    host = (raw or "").strip()
    if not host:
        return ""
    if host.startswith("[") and "]" in host:
        return host.split("]", 1)[0][1:]
    if host.count(":") == 1:
        left, right = host.rsplit(":", 1)
        if right.isdigit():
            return left
    return host


def _parse_xray_ech_output(stdout: str) -> tuple[str, str]:
    """Parse ``xray tls ech`` stdout into (configList, serverKeys) base64 strings."""
    config_b64 = ""
    keys_b64 = ""
    mode: str | None = None
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("ECH config list:"):
            rest = stripped[len("ECH config list:") :].strip()
            mode = "config"
            if rest:
                config_b64 = rest
                mode = None
            continue
        if stripped.startswith("ECH server keys:"):
            rest = stripped[len("ECH server keys:") :].strip()
            mode = "keys"
            if rest:
                keys_b64 = rest
                mode = None
            continue
        if mode == "config" and not config_b64:
            config_b64 = stripped
            mode = None
        elif mode == "keys" and not keys_b64:
            keys_b64 = stripped
            mode = None
    if not config_b64 or not keys_b64:
        raise RuntimeError("Xray did not return ECH config and server keys")
    return config_b64, keys_b64


def discover_tls_certificates() -> list[dict[str, Any]]:
    """Return cert/key file pairs available on the panel host."""
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(
        cert_file: str,
        key_file: str,
        *,
        label: str,
        cert_id: str,
        server_name: str | None = None,
    ) -> None:
        if not (_readable(cert_file) and _readable(key_file)):
            return
        key = (cert_file, key_file)
        if key in seen:
            return
        seen.add(key)
        out.append(
            {
                "id": cert_id,
                "label": label,
                "certificateFile": cert_file,
                "keyFile": key_file,
                "serverName": server_name or "",
            }
        )

    for fullchain in sorted(glob.glob("/etc/letsencrypt/live/*/fullchain.pem")):
        domain = Path(fullchain).parent.name
        priv = str(Path(fullchain).with_name("privkey.pem"))
        add(
            fullchain,
            priv,
            label=f"Let's Encrypt — {domain}",
            cert_id=f"le-{domain}",
            server_name=domain,
        )

    node_cert = "/var/lib/shahkar-node/tls/cert.pem"
    node_key = "/var/lib/shahkar-node/tls/key.pem"
    add(node_cert, node_key, label="Node default TLS", cert_id="node-default")

    bootstrap_cert = "/var/lib/shahkar/ssl/bootstrap.crt"
    bootstrap_key = "/var/lib/shahkar/ssl/bootstrap.key"
    add(bootstrap_cert, bootstrap_key, label="Panel bootstrap (self-signed)", cert_id="panel-bootstrap")

    if XRAY_TLS_DIR.is_dir():
        for cert in sorted(XRAY_TLS_DIR.glob("*.crt")):
            key = cert.with_suffix(".key")
            if key.is_file():
                name = cert.stem
                add(
                    str(cert),
                    str(key),
                    label=f"Generated — {name}",
                    cert_id=f"gen-{name}",
                    server_name=name if not name.startswith("ip-") else "",
                )

    return out


def generate_self_signed(domain: str) -> dict[str, Any]:
    """Create a self-signed cert under /var/lib/shahkar/xray-tls."""
    raw = (domain or "").strip()
    if not raw:
        raise ValueError("Domain or IP is required for self-signed certificate")

    host = _host_from_server_name(raw)
    safe = re.sub(r"[^a-zA-Z0-9._-]", "-", raw)[:64] or "localhost"
    _ensure_tls_dir()
    cert_path = XRAY_TLS_DIR / f"{safe}.crt"
    key_path = XRAY_TLS_DIR / f"{safe}.key"
    _remove_if_writable(cert_path)
    _remove_if_writable(key_path)

    try:
        ipaddress.ip_address(host)
        san = f"IP:{host}"
        cn = host
    except ValueError:
        san = f"DNS:{host}"
        cn = host

    try:
        proc = subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-nodes",
                "-days",
                "365",
                "-newkey",
                "rsa:2048",
                "-keyout",
                str(key_path),
                "-out",
                str(cert_path),
                "-subj",
                f"/CN={cn}",
                "-addext",
                f"subjectAltName={san}",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError as err:
        raise RuntimeError("openssl is not installed on the panel host") from err
    except subprocess.CalledProcessError as err:
        detail = (err.stderr or err.stdout or str(err)).strip()
        raise RuntimeError(f"openssl failed: {detail}") from err

    if not (_readable(str(cert_path)) and _readable(str(key_path))):
        raise RuntimeError("Self-signed certificate was not created")

    return {
        "id": f"gen-{safe}",
        "label": f"Self-signed — {raw}",
        "certificateFile": str(cert_path),
        "keyFile": str(key_path),
        "serverName": host,
    }


def generate_ech(server_name: str) -> dict[str, Any]:
    """Generate ECH server keys and config list via ``xray tls ech``."""
    host = _host_from_server_name(server_name)
    if not host:
        raise ValueError("SNI / server name is required for ECH generation")

    try:
        proc = subprocess.run(
            [XRAY_EXECUTABLE_PATH, "tls", "ech", "--serverName", host],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError as err:
        raise RuntimeError(f"Xray binary not found at {XRAY_EXECUTABLE_PATH}") from err
    except subprocess.CalledProcessError as err:
        detail = (err.stderr or err.stdout or str(err)).strip()
        raise RuntimeError(f"xray tls ech failed: {detail}") from err

    config_b64, keys_b64 = _parse_xray_ech_output(proc.stdout)
    return {
        "serverName": host,
        "echServerKeys": [keys_b64],
        "echConfigList": [config_b64],
    }
