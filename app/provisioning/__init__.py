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
import logging
import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.xray.network_defaults import host_network_tuning_shell

logger = logging.getLogger("uvicorn.error")

__all__ = [
    "ProvisioningError",
    "ProvisioningUnavailable",
    "SSHCredentials",
    "build_install_command",
    "install_docker_shell",
    "push_agent_image_via_ssh",
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


def install_docker_shell() -> str:
    """Bash fragment: ensure ``docker`` exists (get.docker.com, else distro packages)."""
    # get.docker.com is often HTTP-403 from some DCs/countries; fall back to the
    # distro package so provisioning doesn't die with a misleading
    # "curl: (22) ... 403" + exit 127 (docker: command not found).
    # Online install is tried up to 3 times before falling back to apt/dnf/yum.
    return (
        "if ! command -v docker >/dev/null 2>&1; then "
        "echo 'Installing Docker…'; "
        "_np_docker_ok=0; "
        "for _np_dtry in 1 2 3; do "
        "echo \"Downloading Docker installer (attempt $_np_dtry/3)…\"; "
        "if curl -fsSL --connect-timeout 10 --max-time 60 https://get.docker.com -o /tmp/np-get-docker.sh "
        "&& sh /tmp/np-get-docker.sh; then "
        "_np_docker_ok=1; break; "
        "fi; "
        "rm -f /tmp/np-get-docker.sh; "
        "sleep 3; "
        "done; "
        "rm -f /tmp/np-get-docker.sh; "
        "if [ \"$_np_docker_ok\" != 1 ] || ! command -v docker >/dev/null 2>&1; then "
        "echo 'Online Docker install failed — trying distro packages…'; "
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
    agent_image_url: Optional[str] = None,
    agent_image_mirror_url: Optional[str] = None,
    agent_image_from_mirror: bool = False,  # deprecated; ignored (online-first + mirror fallback)
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
    # -k: panel often presents a self-signed / IP cert that nodes do not trust.
    # Bootstrap is best-effort: node→panel HTTPS is often blackholed on Iran↔abroad
    # routes. The panel finishes registration over SSH after the agent is up.
    bootstrap_url = panel_url.rstrip("/") + "/api/node/bootstrap"
    bootstrap_body = (
        f"{{\"token\":{json.dumps(bootstrap_token)},"
        f"\"name\":{json.dumps(node_name)},"
        f"\"address\":\"'\"$PUBLIC_IP\"'\","
        f"\"port\":{int(node_port)},"
        f"\"api_port\":{int(node_api_port)},"
        f"\"role\":{json.dumps(role)},"
        f"\"core_kind\":{json.dumps(core_kind)}"
    )
    if tenant_id is not None:
        bootstrap_body += f',\"tenant_id\":{int(tenant_id)}'
    if region:
        bootstrap_body += f',\"region\":{json.dumps(region)}'
    bootstrap_body += "}"
    bootstrap_curl = (
        "_np_boot_ok=0; "
        "for _np_btry in 1 2; do "
        "echo \"Registering with panel (attempt $_np_btry/2)…\"; "
        f"if curl -fskSL --connect-timeout 8 --max-time 20 -X POST {q(bootstrap_url)} "
        "-H 'Content-Type: application/json' "
        f"-d '{bootstrap_body}'; then "
        "_np_boot_ok=1; break; "
        "fi; "
        "sleep 1; "
        "done; "
        "if [ \"$_np_boot_ok\" != 1 ]; then "
        "echo 'warning: node→panel bootstrap timed out; panel will finish registration'; "
        "fi; "
    )

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

    from config import NODE_AGENT_PACKAGE_URL as _DEFAULT_PKG_URL

    # Online package = GitHub Releases (not the panel). Panel is only for bootstrap API.
    primary_url = (agent_image_url or _DEFAULT_PKG_URL or "").strip()
    if not primary_url:
        raise ProvisioningError("NODE_AGENT_PACKAGE_URL is not configured")
    mirror_url = (agent_image_mirror_url or "").strip()
    _ = agent_image_from_mirror  # deprecated

    wg_host_egress = ""
    if core_kind == "wireguard":
        # Host-network agent: NAT/FORWARD + UDP INPUT so listen ports work
        # without the operator touching the firewall by hand.
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
            "for WP in 51820 51821 51901; do "
            "iptables -C INPUT -p udp --dport \"$WP\" -j ACCEPT 2>/dev/null "
            "|| iptables -I INPUT -p udp --dport \"$WP\" -j ACCEPT; "
            "command -v ufw >/dev/null 2>&1 && ufw allow \"$WP/udp\" comment nexuspanel-wg >/dev/null 2>&1 || true; "
            "done; "
        )

    # Prefer image already on the node. Otherwise: GitHub URL up to 3 times
    # (short timeouts so blocked routes fail fast), then Iran HTTP mirror.
    _ = force_image_rebuild
    if mirror_url and mirror_url != primary_url:
        mirror_branch = (
            "echo 'GitHub image fetch failed after 3 attempts — trying Iran mirror…'; "
            f"if curl -fskSL --connect-timeout 15 --max-time 1800 {q(mirror_url)} | docker load; then "
            ":; "
            "else "
            "echo 'fatal: could not load node agent image from GitHub or Iran mirror' >&2; "
            "exit 1; "
            "fi; "
        )
    else:
        mirror_branch = (
            "echo 'fatal: could not load node agent image from GitHub after 3 attempts' >&2; "
            "exit 1; "
        )
    ensure_image = (
        f"NP_IMG={q(image)}; "
        "if ! docker image inspect \"$NP_IMG\" >/dev/null 2>&1; then "
        "_np_ok=0; "
        "for _np_try in 1 2 3; do "
        "echo \"Downloading node image from GitHub (attempt $_np_try/3)…\"; "
        # Short max-time: Iran/abroad blackholes often accept TCP then stall.
        f"if curl -fskSL --connect-timeout 10 --max-time 90 {q(primary_url)} | docker load; then "
        "_np_ok=1; break; "
        "fi; "
        "sleep 2; "
        "done; "
        "if [ \"$_np_ok\" != 1 ]; then "
        f"{mirror_branch}"
        "fi; "
        "fi; "
        "if ! docker image inspect \"$NP_IMG\" >/dev/null 2>&1; then "
        "echo 'fatal: node agent image not tagged as '\"$NP_IMG\"' after docker load' >&2; "
        "exit 1; "
        "fi; "
    )

    return (
        "set -e; "
        f"{install_docker_shell()}"
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
        "PUBLIC_IP=$(curl -fsSL --connect-timeout 5 --max-time 15 https://api.ipify.org "
        "|| hostname -I | awk '{print $1}'); "
        f"{bootstrap_curl}"
        "echo 'Node agent started.'; "
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
        "cloudfront",
        "403 Forbidden",
        "could not load node agent image",
        "could not download node agent image",
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


def _connect_ssh(creds: SSHCredentials, timeout: int = 30):
    """Open a connected paramiko SSHClient (caller must ``close()``)."""
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

    try:
        client.connect(**connect_kwargs)
    except Exception as exc:
        try:
            client.close()
        except Exception:
            pass
        msg = str(exc)
        if "not found in known_hosts" in msg or "not in known_hosts" in msg:
            raise ProvisioningError(
                f"SSH host key for '{creds.host}' is not trusted "
                "(PROVISIONING_SSH_STRICT_HOST_KEY is on). For a brand-new node, "
                "set PROVISIONING_SSH_STRICT_HOST_KEY=False in the panel .env to "
                "trust it on first connect, or add its key to known_hosts first."
            ) from exc
        raise ProvisioningError(f"SSH provisioning failed: {exc}") from exc
    return client


def push_agent_image_via_ssh(
    creds: SSHCredentials,
    image: Optional[str] = None,
    *,
    timeout: int = 30,
    transfer_timeout: int = 1800,
    force: bool = False,
) -> str:
    """Upload the panel's ``docker save`` of the node agent and ``docker load`` it.

    Bypasses Docker Hub and any need for the node to download from the panel's
    public HTTPS URL — critical when the node DC returns CloudFront 403.

    When ``force`` is False and the node already has the same image ID as the
    panel, the upload is skipped (re-provision / retry in seconds, not half an hour).
    """
    from app.provisioning.agent_image import (
        AgentImageUnavailable,
        cached_image_path,
        image_id,
    )
    from config import NODE_AGENT_IMAGE

    ref = (image or NODE_AGENT_IMAGE).strip() or "nexuspanel/node:latest"
    try:
        local_id = image_id(ref)
        local = cached_image_path(ref)
    except AgentImageUnavailable as exc:
        raise ProvisioningError(str(exc)) from exc

    remote = f"/tmp/nexuspanel-node-agent-{os.getpid()}.tar.gz"
    client = _connect_ssh(creds, timeout=timeout)
    try:
        if not force:
            check = (
                f"docker image inspect --format '{{{{.Id}}}}' {shlex.quote(ref)} 2>/dev/null || true"
            )
            stdin, stdout, stderr = client.exec_command(check, timeout=timeout)
            stdout.channel.recv_exit_status()
            remote_id = (stdout.read().decode("utf-8", "replace") or "").strip()
            if remote_id and remote_id == local_id:
                logger.info(
                    "Node %s already has agent image %s — skipping SSH upload",
                    creds.host,
                    local_id[:19],
                )
                return f"skipped: image already present ({local_id[:19]})"

        sftp = client.open_sftp()
        try:
            sftp.put(str(local), remote)
        finally:
            sftp.close()

        load_cmd = (
            f"set -e; "
            f"docker load -i {shlex.quote(remote)}; "
            f"rm -f {shlex.quote(remote)}; "
            f"docker image inspect {shlex.quote(ref)} >/dev/null"
        )
        stdin, stdout, stderr = client.exec_command(load_cmd, timeout=transfer_timeout)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        if exit_code != 0:
            raise ProvisioningError(
                _summarize_remote_error(err, out, exit_code)
                or f"docker load failed on {creds.host} (exit {exit_code})"
            )
        return out
    finally:
        try:
            client.close()
        except Exception:
            pass


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
    client = _connect_ssh(creds, timeout=timeout)
    try:
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
        raise ProvisioningError(f"SSH provisioning failed: {exc}") from exc
    finally:
        try:
            client.close()
        except Exception:
            pass


def install_control_pubkey(creds: SSHCredentials, timeout: int = 30) -> bool:
    """Authorize the panel's own control-tunnel keypair on the node.

    ``creds`` (the one-time admin-supplied password/key used for the initial
    install) is only ever used transiently during provisioning. Every *later*
    maintenance connection — the SSH local-forward control tunnel used for
    RPyC, post-install tunnel pushes, TLS renewals, restarts — authenticates
    with the panel's own persistent keypair (``resolve_node_ssh_candidates``)
    instead. Without this step that keypair is never actually installed on a
    node added with a password that differs from the panel's generic
    fallback secret, so every maintenance connection permanently fails with
    "Permission denied" and the node silently runs an ever-more-stale config
    forever — the exact failure mode this closes, with no manual
    ``setup_node_ssh_access.py`` run required for any newly added node.

    Returns ``True`` if the key was (already, or newly) authorized.
    """
    from app.provisioning.node_ssh import key_file_path

    key_path = key_file_path()
    pub_path = Path(str(key_path) + ".pub")
    try:
        pubkey = pub_path.read_text().strip()
    except OSError:
        logger.warning("No control-tunnel public key at %s; skipping authorized_keys install", pub_path)
        return False
    if not pubkey:
        return False

    marker = "# nexuspanel-control-tunnel"
    script = (
        "set -e; "
        "mkdir -p ~/.ssh; chmod 700 ~/.ssh; "
        "touch ~/.ssh/authorized_keys; chmod 600 ~/.ssh/authorized_keys; "
        f"grep -qF {shlex.quote(pubkey)} ~/.ssh/authorized_keys 2>/dev/null || "
        f"printf '%s %s\\n' {shlex.quote(pubkey)} {shlex.quote(marker)} >> ~/.ssh/authorized_keys"
    )
    try:
        run_remote_command(creds, script, timeout=timeout, exec_timeout=timeout)
        return True
    except Exception as exc:
        logger.warning("Could not install control-tunnel pubkey on %s: %s", creds.host, exc)
        return False
