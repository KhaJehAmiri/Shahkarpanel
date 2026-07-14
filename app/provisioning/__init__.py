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
import os
import shlex
from dataclasses import dataclass
from typing import Optional

from app.xray.network_defaults import host_network_tuning_shell

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
    client_cert_pem: Optional[str] = None,
    include_awg: bool = False,
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

    ``client_cert_pem`` is the panel's own TLS certificate (the single persistent
    cert it presents on every RPyC/REST connection — see ``app.xray.operations.get_tls``).
    When provided it is written to the node and wired up as ``SSL_CLIENT_CERT_FILE``
    so the node's ``SSLAuthenticator``/uvicorn TLS layer requires and verifies a
    client certificate on every connection (real mutual TLS), instead of accepting
    control connections from anyone who reaches the port (AUDIT_FINDINGS.md H11).
    """
    if not panel_address:
        raise ProvisioningError("panel_address is required")
    if not bootstrap_token:
        raise ProvisioningError("bootstrap_token is required")
    if role not in ("direct", "relay", "transit", "exit"):
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

    client_cert_path = "/var/lib/nexuspanel-node/panel_client_ca.pem"
    cert_env = ""
    write_client_cert = ""
    if client_cert_pem:
        cert_env = f"-e SSL_CLIENT_CERT_FILE={q(client_cert_path)} "
        write_client_cert = (
            f"printf '%s' {q(client_cert_pem)} > {q(client_cert_path)}; "
            f"chmod 600 {q(client_cert_path)}; "
        )

    bundle_url = f"{panel_url.rstrip('/')}/api/nodes/agent-bundle?token={bootstrap_token}"
    image_url = f"{panel_url.rstrip('/')}/api/nodes/agent-image?token={bootstrap_token}"

    wg_host_egress = ""
    if core_kind == "wireguard":
        # Host-network agent: NAT/FORWARD must exist on the host (container may lack iptables).
        wg_host_egress = (
            "WG_OUT=$(ip route get 8.8.8.8 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i==\"dev\") print $(i+1)}'); "
            "if [ -n \"$WG_OUT\" ]; then "
            "for SUB in 10.10.0.0/24 10.11.0.0/24; do "
            "iptables -t nat -C POSTROUTING -s \"$SUB\" -o \"$WG_OUT\" -j MASQUERADE 2>/dev/null "
            "|| iptables -t nat -A POSTROUTING -s \"$SUB\" -o \"$WG_OUT\" -j MASQUERADE; "
            "done; "
            "for IF in wg0 wg1; do "
            "iptables -C FORWARD -i \"$IF\" -j ACCEPT 2>/dev/null || iptables -A FORWARD -i \"$IF\" -j ACCEPT; "
            "iptables -C FORWARD -o \"$IF\" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null "
            "|| iptables -A FORWARD -o \"$IF\" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT; "
            "done; "
            "fi; "
        )

    # Prefer loading a prebuilt image from the panel. Many node DCs block Docker
    # Hub / CloudFront (HTTP 403 on blob pulls), so `docker build` on the node
    # cannot FROM python:*-slim even when the source bundle downloads fine.
    awg_flag = "1" if include_awg else "0"
    if force_image_rebuild:
        ensure_image = (
            f"NP_IMG={q(image)}; "
            "NP_BD=$(mktemp -d); "
            f"curl -fsSL {q(bundle_url)} | tar -xzf - -C \"$NP_BD\"; "
            f"docker build --build-arg INCLUDE_AWG={awg_flag} -t \"$NP_IMG\" \"$NP_BD/node\"; "
            "rm -rf \"$NP_BD\"; "
        )
    else:
        ensure_image = (
            f"NP_IMG={q(image)}; "
            "if ! docker image inspect \"$NP_IMG\" >/dev/null 2>&1; then "
            "echo 'Loading node image from panel…'; "
            f"if ! curl -fsSL --connect-timeout 30 --max-time 1800 {q(image_url)} | docker load; then "
            "echo 'Panel image load failed — falling back to on-node docker build…'; "
            "NP_BD=$(mktemp -d); "
            f"curl -fsSL {q(bundle_url)} | tar -xzf - -C \"$NP_BD\"; "
            f"docker build --build-arg INCLUDE_AWG={awg_flag} -t \"$NP_IMG\" \"$NP_BD/node\"; "
            "rm -rf \"$NP_BD\"; "
            "fi; "
            "fi; "
            "if ! docker image inspect \"$NP_IMG\" >/dev/null 2>&1; then "
            "echo 'fatal: node agent image not available "
            "(panel image download failed and docker build cannot reach Docker Hub)' >&2; "
            "exit 1; "
            "fi; "
        )

    # get.docker.com is often HTTP-403 from some DCs/countries; fall back to the
    # distro package so provisioning doesn't die with a misleading
    # "curl: (22) ... 403" + exit 127 (docker: command not found).
    install_docker = (
        "if ! command -v docker >/dev/null 2>&1; then "
        "echo 'Installing Docker…'; "
        "(curl -fsSL https://get.docker.com -o /tmp/np-get-docker.sh "
        "&& sh /tmp/np-get-docker.sh) || true; "
        "rm -f /tmp/np-get-docker.sh; "
        "if ! command -v docker >/dev/null 2>&1; then "
        "if command -v apt-get >/dev/null 2>&1; then "
        "export DEBIAN_FRONTEND=noninteractive; "
        "apt-get update -y >/dev/null "
        "&& apt-get install -y docker.io docker-compose-v2 2>/dev/null "
        "|| apt-get install -y docker.io; "
        "systemctl enable --now docker 2>/dev/null || service docker start 2>/dev/null || true; "
        "elif command -v dnf >/dev/null 2>&1; then "
        "dnf install -y docker && systemctl enable --now docker; "
        "elif command -v yum >/dev/null 2>&1; then "
        "yum install -y docker && systemctl enable --now docker; "
        "fi; "
        "fi; "
        "if ! command -v docker >/dev/null 2>&1; then "
        "echo 'fatal: could not install Docker "
        "(get.docker.com blocked and no distro package available)' >&2; "
        "exit 1; "
        "fi; "
        "fi; "
    )

    return (
        "set -e; "
        f"{install_docker}"
        # WireGuard needs IPv4 forwarding on the host kernel.
        "sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1 || true; "
        "grep -q '^net.ipv4.ip_forward=1' /etc/sysctl.conf 2>/dev/null "
        "|| echo 'net.ipv4.ip_forward=1' >> /etc/sysctl.conf; "
        f"{host_network_tuning_shell()}; "
        "docker rm -f nexusnode >/dev/null 2>&1 || true; "
        "mkdir -p /var/lib/nexuspanel-node; "
        f"{write_client_cert}"
        f"{ensure_image}"
        # --cap-add=NET_ADMIN + host network let the agent manage the wg interface.
        # ip_forward is set on the host above; --sysctl is invalid with --network=host.
        # --init runs tini as PID 1 so daemons that double-fork and detach
        # (amneziawg-go) get reaped when they exit instead of piling up as
        # zombies under the Python agent, which never calls wait() on them.
        "docker run -d --name nexusnode --restart=always --network=host --init "
        "--cap-add=NET_ADMIN --device /dev/net/tun:/dev/net/tun "
        "-v /var/lib/nexuspanel-node:/var/lib/nexuspanel-node "
        "-e SERVICE_PROTOCOL=rpyc "
        f"{secret_env}"
        f"{cert_env}"
        "\"$NP_IMG\"; "
        f"{wg_host_egress}"
        "PUBLIC_IP=$(curl -fsSL https://api.ipify.org || hostname -I | awk '{print $1}'); "
        f"{bootstrap_curl}"
    )


def ssh_available() -> bool:
    try:
        import paramiko  # noqa: F401
        return True
    except Exception:
        return False


def _summarize_remote_error(stderr: str, stdout: str, exit_code: int, limit: int = 1500) -> str:
    """Return a short, actionable remote failure message (not the full docker log)."""
    blob = (stderr or "").strip() or (stdout or "").strip()
    if not blob:
        return f"remote command failed (exit {exit_code})"
    lines = blob.splitlines()
    markers = (
        "fatal:",
        "error:",
        "ERROR:",
        "failed to",
        "FAILED",
        "exit code",
        "command not found",
        "could not install Docker",
        "get.docker.com",
    )
    hits = [ln for ln in lines if any(m in ln for m in markers)]
    # Prefer the last actionable hit; when exit 127, call out missing commands.
    tail = "\n".join((hits or lines)[-10:])
    if exit_code == 127 and "command not found" not in tail.lower() and "docker" in blob.lower():
        tail = (tail + "\n" if tail else "") + "hint: docker was not installed on the node"
    msg = f"remote command failed (exit {exit_code}): {tail}"
    if len(msg) > limit:
        return msg[: limit - 3] + "..."
    return msg


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
        # Strict mode only makes sense if we actually have host keys to verify
        # against, otherwise every (brand-new) node is rejected and the whole
        # SSH-provision feature is dead on arrival. Load system + user
        # known_hosts so pre-seeded hosts verify.
        for loader in (client.load_system_host_keys, client.load_host_keys):
            try:
                loader() if loader is client.load_system_host_keys \
                    else loader(os.path.expanduser("~/.ssh/known_hosts"))
            except Exception:
                pass
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        # Trust-on-first-use: expected default when bootstrapping a fresh node
        # you own (it has never been seen before).
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

            key_data = io.StringIO(creds.private_key)
            pkey = None
            for key_cls in (
                paramiko.Ed25519Key,
                paramiko.RSAKey,
                paramiko.ECDSAKey,
            ):
                try:
                    key_data.seek(0)
                    pkey = key_cls.from_private_key(key_data)
                    break
                except Exception:
                    continue
            if pkey is None:
                raise ProvisioningError("unsupported SSH private key format")
            connect_kwargs["pkey"] = pkey
        else:
            connect_kwargs["password"] = creds.password
        client.connect(**connect_kwargs)

        stdin, stdout, stderr = client.exec_command(command, timeout=exec_timeout)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        if exit_code != 0:
            raise ProvisioningError(_summarize_remote_error(err, out, exit_code))
        return out
    except ProvisioningError:
        raise
    except Exception as exc:
        msg = str(exc)
        if "not found in known_hosts" in msg or "not in known_hosts" in msg:
            raise ProvisioningError(
                f"SSH host key for '{creds.host}' is not trusted "
                "(PROVISIONING_SSH_STRICT_HOST_KEY is on). For a brand-new node, "
                "set PROVISIONING_SSH_STRICT_HOST_KEY=False in the panel .env to "
                "trust it on first connect, or add its key to known_hosts first."
            ) from exc
        raise ProvisioningError(f"SSH provisioning failed: {exc}") from exc
    finally:
        try:
            client.close()
        except Exception:
            pass
