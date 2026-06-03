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
import shlex
from dataclasses import dataclass
from typing import Optional

__all__ = [
    "ProvisioningError",
    "ProvisioningUnavailable",
    "SSHCredentials",
    "build_install_command",
    "ssh_available",
    "run_remote_command",
]


class ProvisioningError(RuntimeError):
    """Raised when a remote provisioning step fails."""


class ProvisioningUnavailable(ProvisioningError):
    """Raised when SSH provisioning can't run (e.g. paramiko not installed)."""


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
    image: str = "nexuspanel/node:latest",
    node_port: int = 62050,
    node_api_port: int = 62051,
) -> str:
    """Build the self-contained bash command that provisions a fresh server.

    The command is safe to run repeatedly: it installs Docker if missing, (re)starts
    the node-agent container, then registers the node with the panel. All
    user-controlled values are shell-quoted to avoid injection.
    """
    if not panel_address:
        raise ProvisioningError("panel_address is required")
    if not bootstrap_token:
        raise ProvisioningError("bootstrap_token is required")
    if role not in ("direct", "relay", "exit"):
        raise ProvisioningError(f"invalid role: {role}")

    panel_url = panel_address if panel_address.startswith(("http://", "https://")) \
        else f"https://{panel_address}"

    q = shlex.quote
    tenant_field = "" if tenant_id is None else f', \\"tenant_id\\": {int(tenant_id)}'

    return (
        "set -e; "
        "if ! command -v docker >/dev/null 2>&1; then "
        "curl -fsSL https://get.docker.com | sh; fi; "
        f"docker rm -f nexusnode >/dev/null 2>&1 || true; "
        "mkdir -p /var/lib/nexuspanel-node; "
        "docker run -d --name nexusnode --restart=always --network=host "
        "-v /var/lib/nexuspanel-node:/var/lib/nexuspanel-node "
        "-e SERVICE_PROTOCOL=rpyc "
        f"{q(image)}; "
        "PUBLIC_IP=$(curl -fsSL https://api.ipify.org || hostname -I | awk '{print $1}'); "
        f"curl -fsSL -X POST {q(panel_url + '/api/node/bootstrap')} "
        "-H 'Content-Type: application/json' "
        f'-d "{{\\"token\\": \\"{bootstrap_token}\\", '
        f'\\"name\\": \\"{node_name}\\", '
        '\\"address\\": \\"$PUBLIC_IP\\", '
        f'\\"port\\": {int(node_port)}, '
        f'\\"api_port\\": {int(node_api_port)}, '
        f'\\"role\\": \\"{role}\\"{tenant_field}}}"'
    )


def ssh_available() -> bool:
    try:
        import paramiko  # noqa: F401
        return True
    except Exception:
        return False


def run_remote_command(creds: SSHCredentials, command: str, timeout: int = 20) -> str:
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

    client = paramiko.SSHClient()
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

        stdin, stdout, stderr = client.exec_command(command, timeout=timeout * 6)
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
