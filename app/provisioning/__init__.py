"""Add a node by IP + SSH password (phase 6).

The goal: a reseller (or the owner) pastes a server IP and SSH credentials and
the panel turns that bare server into a working node — no manual node-agent
setup. We do this by SSHing in and running an install script that:

1. installs Docker,
2. starts the node-agent container, and
3. self-registers the node against ``POST /api/node/bootstrap`` (reusing the
   phase-2 auto-discovery flow), tagged to the reseller's tenant.

``paramiko`` is an *optional* dependency. When it is missing (or SSH fails) the
API falls back to returning the one-line install command so the user can paste
it into their server manually. The command builder is a pure, tested function.
"""
import json
import shlex
from dataclasses import dataclass
from typing import Optional

__all__ = [
    "ProvisioningError",
    "ProvisioningUnavailable",
    "SSHCredentials",
    "build_install_command",
    "resolve_panel_public_url",
    "ssh_available",
    "run_remote_command",
]


class ProvisioningError(RuntimeError):
    """Raised when a remote provisioning step fails."""


class ProvisioningUnavailable(ProvisioningError):
    """Raised when SSH provisioning can't run (e.g. paramiko not installed)."""


def resolve_panel_public_url() -> str:
    """Base URL remote nodes use to reach this panel (bootstrap callback)."""
    from config import (
        PANEL_PUBLIC_ADDRESS,
        UVICORN_HOST,
        UVICORN_PORT,
        UVICORN_SSL_CERTFILE,
    )

    def _with_scheme(host_port: str) -> str:
        host_port = host_port.strip().rstrip("/")
        if host_port.startswith(("http://", "https://")):
            return host_port
        scheme = "https" if UVICORN_SSL_CERTFILE else "http"
        return f"{scheme}://{host_port}"

    if PANEL_PUBLIC_ADDRESS:
        return _with_scheme(PANEL_PUBLIC_ADDRESS)

    from app.utils.system import get_public_ip

    ip = get_public_ip()
    if ip:
        scheme = "https" if UVICORN_SSL_CERTFILE else "http"
        if (scheme == "https" and UVICORN_PORT == 443) or (scheme == "http" and UVICORN_PORT == 80):
            return f"{scheme}://{ip}"
        return f"{scheme}://{ip}:{UVICORN_PORT}"

    host = (UVICORN_HOST or "").strip()
    if host and host not in ("0.0.0.0", "::"):
        return _with_scheme(f"{host}:{UVICORN_PORT}")

    raise ProvisioningError(
        "Set PANEL_PUBLIC_ADDRESS in .env (e.g. 203.0.113.1:8000) so new nodes can reach this panel."
    )


@dataclass
class SSHCredentials:
    host: str
    port: int = 22
    username: str = "root"
    password: Optional[str] = None
    private_key: Optional[str] = None


def build_install_command(
    panel_address: str,
    bootstrap_token: str,
    node_name: str,
    *,
    tenant_id: Optional[int] = None,
    role: str = "direct",
    core_kind: str = "xray",
    region: Optional[str] = None,
    image: str = "nexuspanel/node:latest",
    node_port: int = 62050,
    node_api_port: int = 62051,
    control_secret: Optional[str] = None,
    force_image_rebuild: bool = False,
) -> str:
    """Build the self-contained bash command that provisions a fresh server.

    The command is safe to run repeatedly: it installs Docker if missing, (re)starts
    the node-agent container, then registers the node with the panel. All
    user-controlled values are shell-quoted to avoid injection.

    The node-agent image already bundles both the Xray (v2ray) core and
    ``wireguard-tools``. To let a single agent serve *both* product families the
    container is started with ``--cap-add=NET_ADMIN`` and IP forwarding enabled so
    it can create/manage the WireGuard interface, and ``NODE_CONTROL_SECRET`` is
    injected (when configured) so the panel's REST control plane is authenticated.
    """
    if not panel_address:
        raise ProvisioningError("panel_address is required")
    if not bootstrap_token:
        raise ProvisioningError("bootstrap_token is required")
    if role not in ("direct", "relay", "exit"):
        raise ProvisioningError(f"invalid role: {role}")
    if core_kind not in ("xray", "wireguard"):
        raise ProvisioningError(f"invalid core_kind: {core_kind}")

    panel_url = panel_address if panel_address.startswith(("http://", "https://")) \
        else f"http://{panel_address}"

    q = shlex.quote
    # Single-line JSON for SSH: -d "..." breaks on inner quotes; heredocs break in sh -c.
    bootstrap_curl = (
        f"curl -fsSL --connect-timeout 15 --max-time 60 -X POST {q(panel_url + '/api/node/bootstrap')} "
        "-H 'Content-Type: application/json' -d "
        f"'{{\"token\":{json.dumps(bootstrap_token)},"
        f"\"name\":{json.dumps(node_name)},"
        f"\"address\":\"'\"$PUBLIC_IP\"'\","
        f"\"port\":{int(node_port)},"
        f"\"api_port\":{int(node_api_port)},"
        f"\"role\":{json.dumps(role)},"
        f"\"core_kind\":{json.dumps(core_kind)}"
    )
    if tenant_id is not None:
        bootstrap_curl += f',\"tenant_id\":{int(tenant_id)}'
    if region:
        bootstrap_curl += f',\"region\":{json.dumps(region)}'
    bootstrap_curl += "}'"

    secret_env = (
        f"-e NODE_CONTROL_SECRET={q(control_secret)} " if control_secret else ""
    )

    bundle_url = f"{panel_url.rstrip('/')}/api/nodes/agent-bundle?token={bootstrap_token}"

    # If the image tag is not on the remote host, try pull then build from the
    # panel's bundled node-agent source (nexuspanel/node is not on Docker Hub).
    # Always rebuild from the panel bundle so agent code updates reach the node.
    ensure_image = (
        f"NP_IMG={q(image)}; "
        "NP_BD=$(mktemp -d); "
        f"curl -fsSL {q(bundle_url)} | tar -xzf - -C \"$NP_BD\"; "
        "docker build -t \"$NP_IMG\" \"$NP_BD/node\"; "
        "rm -rf \"$NP_BD\"; "
    )

    return (
        "set -e; "
        "if ! command -v docker >/dev/null 2>&1; then "
        "curl -fsSL https://get.docker.com | sh; fi; "
        # WireGuard needs IPv4 forwarding on the host kernel.
        "sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1 || true; "
        "grep -q '^net.ipv4.ip_forward=1' /etc/sysctl.conf 2>/dev/null "
        "|| echo 'net.ipv4.ip_forward=1' >> /etc/sysctl.conf; "
        "docker rm -f nexusnode >/dev/null 2>&1 || true; "
        "mkdir -p /var/lib/nexuspanel-node; "
        f"{ensure_image}"
        # --cap-add=NET_ADMIN + host network let the agent manage the wg interface.
        # ip_forward is set on the host above; --sysctl is invalid with --network=host.
        "docker run -d --name nexusnode --restart=always --network=host "
        "--cap-add=NET_ADMIN "
        "-v /var/lib/nexuspanel-node:/var/lib/nexuspanel-node "
        "-e SERVICE_PROTOCOL=rpyc "
        f"{secret_env}"
        "\"$NP_IMG\"; "
        "PUBLIC_IP=$(curl -fsSL https://api.ipify.org || hostname -I | awk '{print $1}'); "
        f"{bootstrap_curl}"
    )


def ssh_available() -> bool:
    try:
        import paramiko  # noqa: F401
        return True
    except Exception:
        return False


def run_remote_command(
    creds: SSHCredentials,
    command: str,
    timeout: int = 30,
    exec_timeout: int = 600,
) -> str:
    """Run ``command`` on the remote host over SSH, returning combined output.

    Raises :class:`ProvisioningUnavailable` if paramiko isn't installed and
    :class:`ProvisioningError` on connection/exec failure.
    """
    try:
        import paramiko
    except Exception as exc:  # pragma: no cover - exercised when paramiko absent
        raise ProvisioningUnavailable(
            "paramiko is not installed; cannot SSH. Use the returned install "
            "command to provision the server manually."
        ) from exc

    from config import PROVISIONING_SSH_STRICT_HOST_KEY

    client = paramiko.SSHClient()
    if PROVISIONING_SSH_STRICT_HOST_KEY:
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        connect_kwargs = dict(
            hostname=creds.host,
            port=creds.port,
            username=creds.username,
            timeout=timeout,
            banner_timeout=timeout,
            auth_timeout=timeout,
        )
        if creds.private_key:
            import io
            pkey = paramiko.RSAKey.from_private_key(io.StringIO(creds.private_key))
            connect_kwargs["pkey"] = pkey
        else:
            connect_kwargs["password"] = creds.password
        client.connect(**connect_kwargs)

        stdin, stdout, stderr = client.exec_command(command, timeout=exec_timeout)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        if exit_code != 0:
            raise ProvisioningError(
                f"remote command failed (exit {exit_code}): {err.strip() or out.strip()}"
            )
        return out
    except ProvisioningError:
        raise
    except Exception as exc:
        raise ProvisioningError(f"SSH provisioning failed: {exc}") from exc
    finally:
        try:
            client.close()
        except Exception:
            pass
