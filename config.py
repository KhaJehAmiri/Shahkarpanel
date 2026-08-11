from decouple import config
from dotenv import load_dotenv
import os
from pathlib import Path

RUNTIME_ENV_PATH = Path(
    os.environ.get("SHAHKAR_RUNTIME_ENV", "/var/lib/shahkar/.env")
)


def _load_env_file() -> None:
    """Load repo .env then runtime secrets from outside the git checkout.

    Docker Compose may inject both via ``env_file``; this mirrors that order
    when the panel runs directly (``python main.py``) or when only one file
    was loaded. Runtime secrets always win over repo .env (M16).
    """
    repo_env = Path(os.environ.get("DOTENV_PATH", ".env"))
    for path in (repo_env, RUNTIME_ENV_PATH):
        if not path.is_file() or not os.access(path, os.R_OK):
            continue
        try:
            load_dotenv(path, override=(path == RUNTIME_ENV_PATH))
        except OSError:
            pass


_load_env_file()


SQLALCHEMY_DATABASE_URL = config("SQLALCHEMY_DATABASE_URL", default="sqlite:///db.sqlite3")
SQLALCHEMY_POOL_SIZE = config("SQLALCHEMY_POOL_SIZE", cast=int, default=10)
# Correctly-spelled env var, with a fallback to the historical misspelling so
# existing .env files that set SQLIALCHEMY_MAX_OVERFLOW keep working.
SQLALCHEMY_MAX_OVERFLOW = config(
    "SQLALCHEMY_MAX_OVERFLOW",
    cast=int,
    default=config("SQLIALCHEMY_MAX_OVERFLOW", cast=int, default=30),
)
# Backwards-compatible alias for any external importers of the old name.
SQLIALCHEMY_MAX_OVERFLOW = SQLALCHEMY_MAX_OVERFLOW

# Optional Redis URL used by the event bus / cache layer. When empty, the panel
# falls back to an in-process backend (single-instance only). Required for HA.
REDIS_URL = config("REDIS_URL", default="")

# How long to keep persisted events in the audit log. Set <= 0 to disable
# automatic cleanup (keep forever).
EVENTS_RETENTION_DAYS = config("EVENTS_RETENTION_DAYS", cast=int, default=30)

# Emit logs as structured JSON (useful for log aggregation / observability).
LOG_JSON = config("LOG_JSON", cast=bool, default=False)

# Optional static token for scraping the Prometheus /api/metrics endpoint.
# When set, send header `Authorization: Bearer <METRICS_TOKEN>` only — query
# `?token=` is not accepted (tokens in URLs leak via logs and reverse proxies).
# When empty, a sudo admin bearer token is required.
METRICS_TOKEN = config("METRICS_TOKEN", default="")

# Cluster / reliability
# Token allowing a node to self-register via POST /api/node/bootstrap.
# Leave empty to disable auto-discovery.
NODE_BOOTSTRAP_TOKEN = config("NODE_BOOTSTRAP_TOKEN", default="")
# Shared secret for REST node control API (header X-Shahkar-Control-Secret). Empty = disabled.
NODE_CONTROL_SECRET = config("NODE_CONTROL_SECRET", default="")
# Node agent certs are self-signed with no SAN (see node/certificate.py), so the
# panel always pins the exact cert content on first connect and rejects any later
# cert change as a possible MITM (TOFU, see verify_or_capture_pin/server_cert_sha256)
# regardless of this flag. NODE_SSL_VERIFY additionally enables strict hostname/SAN
# matching on top of that pin — only turn this on if nodes are provisioned with
# CA-issued certs whose SAN matches their address, otherwise connections will fail.
NODE_SSL_VERIFY = config("NODE_SSL_VERIFY", cast=bool, default=False)
NODE_BOOTSTRAP_MAX_ATTEMPTS = config("NODE_BOOTSTRAP_MAX_ATTEMPTS", cast=int, default=20)
NODE_BOOTSTRAP_WINDOW_SECONDS = config("NODE_BOOTSTRAP_WINDOW_SECONDS", cast=int, default=3600)
LOGIN_MAX_ATTEMPTS = config("LOGIN_MAX_ATTEMPTS", cast=int, default=10)
LOGIN_MAX_WINDOW_SECONDS = config("LOGIN_MAX_WINDOW_SECONDS", cast=int, default=900)
# Optional OIDC/OAuth admin SSO (leave issuer empty to disable).
OIDC_ISSUER = config("OIDC_ISSUER", default="")
OIDC_CLIENT_ID = config("OIDC_CLIENT_ID", default="")
OIDC_CLIENT_SECRET = config("OIDC_CLIENT_SECRET", default="")
OIDC_REDIRECT_URI = config("OIDC_REDIRECT_URI", default="")
OIDC_USERNAME_CLAIM = config("OIDC_USERNAME_CLAIM", default="preferred_username")
# Optional Content-Security-Policy header value (empty = omit header).
SECURITY_CSP = config("SECURITY_CSP", default="")
# False = AutoAddPolicy for new node SSH (one-click provision). Set True to require
# known_hosts / strict host-key checks (AUDIT M15).
PROVISIONING_SSH_STRICT_HOST_KEY = config("PROVISIONING_SSH_STRICT_HOST_KEY", cast=bool, default=False)
# Interval (seconds) for the cluster failover detector. 0 disables it.
CLUSTER_FAILOVER_CHECK_INTERVAL = config("CLUSTER_FAILOVER_CHECK_INTERVAL", cast=int, default=0)

# Panel self-update: GitHub repo for version check when git is unavailable (Docker).
PANEL_GITHUB_REPO = config("PANEL_GITHUB_REPO", default="KhaJehAmiri/Shahkarpanel")
PANEL_GITHUB_BRANCH = config("PANEL_GITHUB_BRANCH", default="master")
# A node must stay in error for this many seconds before being considered down.
CLUSTER_NODE_DOWN_SECONDS = config("CLUSTER_NODE_DOWN_SECONDS", cast=int, default=180)
# Automatically disable a persistently-down node (failover). Off by default.
CLUSTER_AUTO_DISABLE_DOWN_NODES = config("CLUSTER_AUTO_DISABLE_DOWN_NODES", cast=bool, default=False)
# Attempt an automatic reconnect for a down node before declaring it down. On by
# default: cheap self-heal for transient blips (network, node restart).
CLUSTER_AUTO_RECONNECT_DOWN_NODES = config("CLUSTER_AUTO_RECONNECT_DOWN_NODES", cast=bool, default=True)

# OpenTelemetry tracing
OTEL_ENABLED = config("OTEL_ENABLED", cast=bool, default=False)
OTEL_EXPORTER_OTLP_ENDPOINT = config("OTEL_EXPORTER_OTLP_ENDPOINT", default="http://127.0.0.1:4317")
OTEL_SERVICE_NAME = config("OTEL_SERVICE_NAME", default="shahkar")

# High availability (phase 4). When multiple panel instances share one DB,
# only the elected leader runs singleton scheduler jobs (usage recording,
# notifications, backups, failover). Requires REDIS_URL; without it the single
# instance is always the leader.
HA_ENABLED = config("HA_ENABLED", cast=bool, default=False)
# Unique id for this instance; defaults to hostname:pid when empty.
HA_INSTANCE_ID = config("HA_INSTANCE_ID", default="")
# Seconds the leader lock is held before it must be renewed/expires.
HA_LEADER_TTL = config("HA_LEADER_TTL", cast=int, default=15)

# Smart routing (phase 4). Strategy used to order/select nodes for clients:
# 'latency' | 'region' | 'load' | 'round_robin'. Gated by the 'smart_routing' flag.
ROUTING_STRATEGY = config("ROUTING_STRATEGY", default="latency")

# Traffic intelligence (phase 5). Background scan interval in seconds; 0 disables
# the scheduled scan (the API endpoints still work on-demand). Thresholds tune
# the heuristics.
INTELLIGENCE_SCAN_INTERVAL = config("INTELLIGENCE_SCAN_INTERVAL", cast=int, default=0)
# A user is "heavy" if its windowed usage exceeds this many times the median.
INTELLIGENCE_HEAVY_FACTOR = config("INTELLIGENCE_HEAVY_FACTOR", cast=float, default=3.0)
# Flag users predicted to exhaust their data limit within this many hours.
INTELLIGENCE_EXHAUSTION_WINDOW_HOURS = config(
    "INTELLIGENCE_EXHAUSTION_WINDOW_HOURS", cast=int, default=48
)
# Node latency (ms) above which a node is flagged as at-risk.
INTELLIGENCE_NODE_LATENCY_MS = config("INTELLIGENCE_NODE_LATENCY_MS", cast=float, default=500.0)

# Panel hosting region for tunnel UX: iran | foreign (empty = auto-detect via GeoIP).
PANEL_REGION = config("PANEL_REGION", default="")

# White-label / reseller / provisioning / tunnels (phase 6)
# Publicly reachable address resellers' provisioned nodes use to reach this
# panel (host or host:port). Falls back to UVICORN_HOST:UVICORN_PORT.
PANEL_PUBLIC_ADDRESS = config("PANEL_PUBLIC_ADDRESS", default="")
# Container image deployed on a reseller server when provisioning a node.
# Must be a node-agent image reachable by the target server's Docker. Override
# with your own published image (see scripts/ for building a node image).
NODE_AGENT_IMAGE = config("NODE_AGENT_IMAGE", default="shahkar/node:latest")
# Primary online URL for the gzipped ``docker save`` of NODE_AGENT_IMAGE
# (GitHub Releases). Nodes curl this first (3 attempts), then Iran mirror.
NODE_AGENT_PACKAGE_URL = config(
    "NODE_AGENT_PACKAGE_URL",
    default=(
        "https://github.com/KhaJehAmiri/Shahkarpanel/releases/download/"
        "node-agent/shahkar-node-agent-image.tar.gz"
    ),
)
# Domestic HTTP mirror — used only after online/GitHub fetch fails 3x.
# Example: http://mirror.example.com/shahkar/node-agent-image.tar.gz
NODE_AGENT_MIRROR_URL = config("NODE_AGENT_MIRROR_URL", default="")
# SSH connect timeout (seconds) when auto-provisioning a node.
NODE_PROVISION_SSH_TIMEOUT = config("NODE_PROVISION_SSH_TIMEOUT", cast=int, default=30)
# Max seconds to wait for the remote install script (Docker build + agent start).
NODE_PROVISION_EXEC_TIMEOUT = config("NODE_PROVISION_EXEC_TIMEOUT", cast=int, default=1200)
# Default ports a provisioned node listens on.
NODE_DEFAULT_PORT = config("NODE_DEFAULT_PORT", cast=int, default=62050)
NODE_DEFAULT_API_PORT = config("NODE_DEFAULT_API_PORT", cast=int, default=62051)

# Backup & disaster recovery
BACKUP_DIR = config("BACKUP_DIR", default="/var/lib/shahkar/backups")
# Interval between automatic backups in hours. 0 disables scheduled backups.
BACKUP_INTERVAL_HOURS = config("BACKUP_INTERVAL_HOURS", cast=int, default=0)
# Number of most-recent backups to keep on disk. <= 0 keeps all.
BACKUP_RETENTION_COUNT = config("BACKUP_RETENTION_COUNT", cast=int, default=7)
# Whether to include the .env file (contains secrets) in the backup archive.
BACKUP_INCLUDE_ENV = config("BACKUP_INCLUDE_ENV", cast=bool, default=False)

UVICORN_HOST = config("UVICORN_HOST", default="0.0.0.0")
UVICORN_PORT = config("UVICORN_PORT", cast=int, default=8000)
UVICORN_UDS = config("UVICORN_UDS", default=None)
UVICORN_SSL_CERTFILE = config("UVICORN_SSL_CERTFILE", default=None)
UVICORN_SSL_KEYFILE = config("UVICORN_SSL_KEYFILE", default=None)
UVICORN_SSL_CA_TYPE = config("UVICORN_SSL_CA_TYPE", default="public").lower()
DASHBOARD_PATH = config("DASHBOARD_PATH", default="/dashboard/")

DEBUG = config("DEBUG", default=False, cast=bool)
DOCS = config("DOCS", default=False, cast=bool)

# Comma-separated origins; empty = do not emit permissive CORS (same-origin only).
ALLOWED_ORIGINS = [
    o.strip() for o in config("ALLOWED_ORIGINS", default="").split(",") if o.strip()
]
CORS_ALLOW_CREDENTIALS = config("CORS_ALLOW_CREDENTIALS", cast=bool, default=True)

VITE_BASE_API = f"http://127.0.0.1:{UVICORN_PORT}/api/" \
    if DEBUG and config("VITE_BASE_API", default="/api/") == "/api/" \
    else config("VITE_BASE_API", default="/api/")

XRAY_JSON = config("XRAY_JSON", default="./xray_config.json")
WARP_DATA = config("WARP_DATA", default="./warp_account.json")

# Automatic WARP outbound health-check + self-heal (see app/jobs/warp_health.py).
# The default hostname almost always resolves to the same anycast IP, so a
# blocked/dead endpoint needs an alternate IP:port to actually recover — not
# just a fresh DNS lookup. Candidates are "ip:port" pairs from Cloudflare's
# published consumer-WARP ingress ranges; tune per-network if your ISP blocks
# a different subset. https://developers.cloudflare.com/cloudflare-one/connections/connect-devices/warp/deployment/firewall/
JOB_WARP_HEALTH_CHECK_ENABLED = config("JOB_WARP_HEALTH_CHECK_ENABLED", cast=bool, default=True)
JOB_WARP_HEALTH_CHECK_INTERVAL = config("JOB_WARP_HEALTH_CHECK_INTERVAL", cast=int, default=60)
WARP_HEALTH_FAILURE_THRESHOLD = config("WARP_HEALTH_FAILURE_THRESHOLD", cast=int, default=2)
WARP_HEALTH_REMEDIATION_COOLDOWN = config("WARP_HEALTH_REMEDIATION_COOLDOWN", cast=int, default=180)
# Auto re-apply Reality/WG tunnels after node flaps (no manual Apply).
JOB_TUNNEL_HEAL_ENABLED = config("JOB_TUNNEL_HEAL_ENABLED", cast=bool, default=True)
JOB_TUNNEL_HEAL_INTERVAL = config("JOB_TUNNEL_HEAL_INTERVAL", cast=int, default=60)
# Require several consecutive unhealthy probes before Apply (avoids flap loops).
TUNNEL_HEAL_FAILURE_THRESHOLD = config("TUNNEL_HEAL_FAILURE_THRESHOLD", cast=int, default=3)
TUNNEL_HEAL_COOLDOWN_SEC = config("TUNNEL_HEAL_COOLDOWN_SEC", cast=int, default=180)
WARP_CANDIDATE_ENDPOINTS = [
    ep.strip()
    for ep in config(
        "WARP_CANDIDATE_ENDPOINTS",
        default=(
            "162.159.192.1:2408,162.159.192.1:500,162.159.192.1:1701,162.159.192.1:4500,"
            "188.114.96.1:2408,188.114.97.1:2408,162.159.195.1:2408,188.114.96.1:894"
        ),
    ).split(",")
    if ep.strip()
]
XRAY_FALLBACKS_INBOUND_TAG = config("XRAY_FALLBACKS_INBOUND_TAG", cast=str, default="") or config(
    "XRAY_FALLBACK_INBOUND_TAG", cast=str, default=""
)
XRAY_EXECUTABLE_PATH = config("XRAY_EXECUTABLE_PATH", default="/usr/local/bin/xray")
XRAY_ASSETS_PATH = config("XRAY_ASSETS_PATH", default="/usr/local/share/xray")
XRAY_EXCLUDE_INBOUND_TAGS = config("XRAY_EXCLUDE_INBOUND_TAGS", default='').split()
XRAY_SUBSCRIPTION_URL_PREFIX = config("XRAY_SUBSCRIPTION_URL_PREFIX", default="").strip("/")
XRAY_SUBSCRIPTION_PATH = config("XRAY_SUBSCRIPTION_PATH", default="sub").strip("/")
# 3x-ui style CDN: hosts override subscription address/port/TLS; Xray bind is separate.
# When True, CDN ws/grpc inbounds are rebound to 127.0.0.1 at runtime. Default False
# keeps inbound listen on 0.0.0.0 (public bind).
XRAY_CDN_RUNTIME_ENABLED = config("XRAY_CDN_RUNTIME_ENABLED", cast=bool, default=False)
# Optional origin nginx vhosts for proxy domains only (never the panel web vhost).
_cdn_origin_raw = config("XRAY_CDN_ORIGIN_NGINX", default="")
if _cdn_origin_raw == "":
    XRAY_CDN_ORIGIN_NGINX = config("XRAY_EDGE_PROXY_ENABLED", cast=bool, default=True)
else:
    XRAY_CDN_ORIGIN_NGINX = config("XRAY_CDN_ORIGIN_NGINX", cast=bool)
# Deprecated alias — use XRAY_CDN_ORIGIN_NGINX.
XRAY_EDGE_PROXY_ENABLED = XRAY_CDN_ORIGIN_NGINX

TELEGRAM_API_TOKEN = config("TELEGRAM_API_TOKEN", default="")
TELEGRAM_ADMIN_ID = config(
    'TELEGRAM_ADMIN_ID',
    default="",
    cast=lambda v: [int(i) for i in filter(str.isdigit, (s.strip() for s in v.split(',')))]
)
TELEGRAM_PROXY_URL = config("TELEGRAM_PROXY_URL", default="")
TELEGRAM_LOGGER_CHANNEL_ID = config("TELEGRAM_LOGGER_CHANNEL_ID", cast=int, default=0)
TELEGRAM_DEFAULT_VLESS_FLOW = config("TELEGRAM_DEFAULT_VLESS_FLOW", default="")

JWT_ACCESS_TOKEN_EXPIRE_MINUTES = config("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", cast=int, default=60)
JWT_REFRESH_TOKEN_EXPIRE_DAYS = config("JWT_REFRESH_TOKEN_EXPIRE_DAYS", cast=int, default=7)

CUSTOM_TEMPLATES_DIRECTORY = config("CUSTOM_TEMPLATES_DIRECTORY", default=None)
SUBSCRIPTION_PAGE_TEMPLATE = config("SUBSCRIPTION_PAGE_TEMPLATE", default="subscription/index.html")
HOME_PAGE_TEMPLATE = config("HOME_PAGE_TEMPLATE", default="home/index.html")

CLASH_SUBSCRIPTION_TEMPLATE = config("CLASH_SUBSCRIPTION_TEMPLATE", default="clash/default.yml")
CLASH_SETTINGS_TEMPLATE = config("CLASH_SETTINGS_TEMPLATE", default="clash/settings.yml")

SINGBOX_SUBSCRIPTION_TEMPLATE = config("SINGBOX_SUBSCRIPTION_TEMPLATE", default="singbox/default.json")
SINGBOX_SETTINGS_TEMPLATE = config("SINGBOX_SETTINGS_TEMPLATE", default="singbox/settings.json")

MUX_TEMPLATE = config("MUX_TEMPLATE", default="mux/default.json")

V2RAY_SUBSCRIPTION_TEMPLATE = config("V2RAY_SUBSCRIPTION_TEMPLATE", default="v2ray/default.json")
V2RAY_SETTINGS_TEMPLATE = config("V2RAY_SETTINGS_TEMPLATE", default="v2ray/settings.json")

USER_AGENT_TEMPLATE = config("USER_AGENT_TEMPLATE", default="user_agent/default.json")
GRPC_USER_AGENT_TEMPLATE = config("GRPC_USER_AGENT_TEMPLATE", default="user_agent/grpc.json")

EXTERNAL_CONFIG = config("EXTERNAL_CONFIG", default="", cast=str)
LOGIN_NOTIFY_WHITE_LIST = [ip.strip() for ip in config("LOGIN_NOTIFY_WHITE_LIST",
                                                       default="", cast=str).split(",") if ip.strip()]

# Admin login IP allow-list. Comma-separated IPs or CIDRs (v4/v6). When set,
# admin token issuance is only allowed from these networks. Empty = allow all
# (backward compatible).
ADMIN_IP_ALLOWLIST = [ip.strip() for ip in config("ADMIN_IP_ALLOWLIST",
                                                  default="", cast=str).split(",") if ip.strip()]

USE_CUSTOM_JSON_DEFAULT = config("USE_CUSTOM_JSON_DEFAULT", default=False, cast=bool)
USE_CUSTOM_JSON_FOR_V2RAYN = config("USE_CUSTOM_JSON_FOR_V2RAYN", default=False, cast=bool)
USE_CUSTOM_JSON_FOR_V2RAYNG = config("USE_CUSTOM_JSON_FOR_V2RAYNG", default=False, cast=bool)
USE_CUSTOM_JSON_FOR_STREISAND = config("USE_CUSTOM_JSON_FOR_STREISAND", default=False, cast=bool)
USE_CUSTOM_JSON_FOR_HAPP = config("USE_CUSTOM_JSON_FOR_HAPP", default=False, cast=bool)

NOTIFY_STATUS_CHANGE = config("NOTIFY_STATUS_CHANGE", default=True, cast=bool)
NOTIFY_USER_CREATED = config("NOTIFY_USER_CREATED", default=True, cast=bool)
NOTIFY_USER_UPDATED = config("NOTIFY_USER_UPDATED", default=True, cast=bool)
NOTIFY_USER_DELETED = config("NOTIFY_USER_DELETED", default=True, cast=bool)
NOTIFY_USER_DATA_USED_RESET = config("NOTIFY_USER_DATA_USED_RESET", default=True, cast=bool)
NOTIFY_USER_SUB_REVOKED = config("NOTIFY_USER_SUB_REVOKED", default=True, cast=bool)
NOTIFY_IF_DATA_USAGE_PERCENT_REACHED = config("NOTIFY_IF_DATA_USAGE_PERCENT_REACHED", default=True, cast=bool)
NOTIFY_IF_DAYS_LEFT_REACHED = config("NOTIFY_IF_DAYS_LEFT_REACHED", default=True, cast=bool)
NOTIFY_LOGIN = config("NOTIFY_LOGIN", default=True, cast=bool)

ACTIVE_STATUS_TEXT = config("ACTIVE_STATUS_TEXT", default="Active")
EXPIRED_STATUS_TEXT = config("EXPIRED_STATUS_TEXT", default="Expired")
LIMITED_STATUS_TEXT = config("LIMITED_STATUS_TEXT", default="Limited")
DISABLED_STATUS_TEXT = config("DISABLED_STATUS_TEXT", default="Disabled")
ONHOLD_STATUS_TEXT = config("ONHOLD_STATUS_TEXT", default="On-Hold")

# Shown as proxy/server name inside VPN apps when subscription export is blocked.
SUB_BLOCKED_DATA_LIMIT_MESSAGE = config(
    "SUB_BLOCKED_DATA_LIMIT_MESSAGE",
    default="🪫 حجم اینترنت تمام شده — برای تمدید با پشتیبانی تماس بگیرید",
)
SUB_BLOCKED_EXPIRED_MESSAGE = config(
    "SUB_BLOCKED_EXPIRED_MESSAGE",
    default="⌛ اعتبار اشتراک تمام شده — برای تمدید با پشتیبانی تماس بگیرید",
)
SUB_BLOCKED_INACTIVE_MESSAGE = config(
    "SUB_BLOCKED_INACTIVE_MESSAGE",
    default="❌ حساب غیرفعال است — با پشتیبانی تماس بگیرید",
)
SUB_BLOCKED_DEVICE_LIMIT_MESSAGE = config(
    "SUB_BLOCKED_DEVICE_LIMIT_MESSAGE",
    default="📱 محدودیت دستگاه — اتصال روی دستگاه دوم شناسایی شد. کانفیگ‌ها به مدت {minutes} دقیقه مخفی هستند",
)
SUB_BLOCKED_FAMILY_SCHEDULE_MESSAGE = config(
    "SUB_BLOCKED_FAMILY_SCHEDULE_MESSAGE",
    default="👨‍👩‍👧 Family Guard — خارج از ساعت مجاز یا سقف روزانه",
)

USERS_AUTODELETE_DAYS = config("USERS_AUTODELETE_DAYS", default=-1, cast=int)
USER_AUTODELETE_INCLUDE_LIMITED_ACCOUNTS = config("USER_AUTODELETE_INCLUDE_LIMITED_ACCOUNTS", default=False, cast=bool)


# Sudo bootstrap: prefer SUDO_PASSWORD_HASH (bcrypt). Plain SUDO_PASSWORD is legacy.
SUDO_USERNAME = config("SUDO_USERNAME", default="")
SUDO_PASSWORD = config("SUDO_PASSWORD", default="")
SUDO_PASSWORD_HASH = config("SUDO_PASSWORD_HASH", default="")
SUDOERS = (
    {SUDO_USERNAME: SUDO_PASSWORD}
    if SUDO_USERNAME and SUDO_PASSWORD and not SUDO_PASSWORD_HASH
    else {}
)

if SUDO_PASSWORD and SUDO_PASSWORD_HASH:
    import logging
    logging.getLogger("shahkar.config").warning(
        "SUDO_PASSWORD is ignored when SUDO_PASSWORD_HASH is set"
    )
elif SUDO_PASSWORD and not SUDO_PASSWORD_HASH:
    import logging
    logging.getLogger("shahkar.config").warning(
        "SUDO_PASSWORD is set without SUDO_PASSWORD_HASH — use bcrypt hash in production"
    )


WEBHOOK_ADDRESS = config(
    'WEBHOOK_ADDRESS',
    default="",
    cast=lambda v: [address.strip() for address in v.split(',')] if v else []
)
WEBHOOK_SECRET = config("WEBHOOK_SECRET", default=None)

# recurrent notifications

# timeout between each retry of sending a notification in seconds
RECURRENT_NOTIFICATIONS_TIMEOUT = config("RECURRENT_NOTIFICATIONS_TIMEOUT", default=180, cast=int)
# how many times to try after ok response not recevied after sending a notifications
NUMBER_OF_RECURRENT_NOTIFICATIONS = config("NUMBER_OF_RECURRENT_NOTIFICATIONS", default=3, cast=int)

# sends a notification when the user uses this much of thier data
NOTIFY_REACHED_USAGE_PERCENT = config(
    "NOTIFY_REACHED_USAGE_PERCENT",
    default="80",
    cast=lambda v: [int(p.strip()) for p in v.split(',')] if v else []
)

# sends a notification when there is n days left of their service
NOTIFY_DAYS_LEFT = config(
    "NOTIFY_DAYS_LEFT",
    default="3",
    cast=lambda v: [int(d.strip()) for d in v.split(',')] if v else []
)

DISABLE_RECORDING_NODE_USAGE = config("DISABLE_RECORDING_NODE_USAGE", cast=bool, default=False)

# headers: profile-update-interval, support-url, profile-title
SUB_UPDATE_INTERVAL = config("SUB_UPDATE_INTERVAL", default="12")
SUB_SUPPORT_URL = config("SUB_SUPPORT_URL", default="https://t.me/")
SUB_PROFILE_TITLE = config("SUB_PROFILE_TITLE", default="Shahkar")
SUB_PROFILE_TITLE_DYNAMIC = config("SUB_PROFILE_TITLE_DYNAMIC", default=True, cast=bool)

# Installer / first-run defaults
PANEL_DEFAULT_LANG = config("PANEL_DEFAULT_LANG", default="en")
PANEL_TITLE = config("PANEL_TITLE", default="Shahkar")
PRIMARY_COLOR = config("PRIMARY_COLOR", default="#2ee0c4")

# discord webhook log
DISCORD_WEBHOOK_URL = config("DISCORD_WEBHOOK_URL", default="")

# SigmaGuard push (FCM / APNs). Leave empty to skip delivery (tokens still stored).
FCM_SERVER_KEY = config("FCM_SERVER_KEY", default="")
FCM_SERVICE_ACCOUNT_JSON = config("FCM_SERVICE_ACCOUNT_JSON", default="")
APNS_KEY_PATH = config("APNS_KEY_PATH", default="")
APNS_KEY_ID = config("APNS_KEY_ID", default="")
APNS_TEAM_ID = config("APNS_TEAM_ID", default="")
APNS_BUNDLE_ID = config("APNS_BUNDLE_ID", default="")
APNS_USE_SANDBOX = config("APNS_USE_SANDBOX", cast=bool, default=True)


# Interval jobs, all values are in seconds
JOB_CORE_HEALTH_CHECK_INTERVAL = config("JOB_CORE_HEALTH_CHECK_INTERVAL", cast=int, default=10)
# When the main core's *process* is alive but its gRPC stats API does not answer,
# a single timeout is almost always transient (CPU spike, GC pause, brief gRPC
# congestion) — restarting the whole core on it disconnects every user for
# nothing. Retry the probe a few times within the tick, and only restart once
# this many *consecutive* health ticks have all failed.
#   CORE_HEALTH_API_TIMEOUT           — per-probe gRPC timeout (seconds)
#   CORE_HEALTH_API_RETRIES           — extra in-tick retries after the first miss
#   CORE_HEALTH_API_FAILURE_THRESHOLD — consecutive failed ticks before restart
#                                       (1 restores the old restart-on-first-miss)
CORE_HEALTH_API_TIMEOUT = config("CORE_HEALTH_API_TIMEOUT", cast=int, default=3)
CORE_HEALTH_API_RETRIES = config("CORE_HEALTH_API_RETRIES", cast=int, default=1)
CORE_HEALTH_API_FAILURE_THRESHOLD = config("CORE_HEALTH_API_FAILURE_THRESHOLD", cast=int, default=3)

# Every core restart is a brief all-user outage between the old process dying and
# the new one binding the inbound ports. Xray exits within well under a second on
# SIGTERM and its ports free immediately, so the normal outage is ~1s; these caps
# only bound the *worst* case (a wedged process or a lingering port owner).
#   XRAY_RESTART_STOP_TIMEOUT         — graceful SIGTERM wait before SIGKILL (s)
#   XRAY_RESTART_PORT_RECLAIM_TIMEOUT — how long to wait for inbound ports to free (s)
XRAY_RESTART_STOP_TIMEOUT = config("XRAY_RESTART_STOP_TIMEOUT", cast=float, default=3.0)
XRAY_RESTART_PORT_RECLAIM_TIMEOUT = config("XRAY_RESTART_PORT_RECLAIM_TIMEOUT", cast=float, default=12.0)
JOB_CORE_USER_RECONCILE_INTERVAL = config("JOB_CORE_USER_RECONCILE_INTERVAL", cast=int, default=45)
# Opt-in: periodically flush idle AWG peer endpoints during the health-check tick.
# Off by default — endpoint reconcile (`reconcile_awg_endpoints`) already runs every tick.
JOB_AWG_FLUSH_STALE_PEERS = config("JOB_AWG_FLUSH_STALE_PEERS", cast=bool, default=False)
JOB_RECORD_NODE_USAGES_INTERVAL = config("JOB_RECORD_NODE_USAGES_INTERVAL", cast=int, default=30)
JOB_RECORD_USER_USAGES_INTERVAL = config("JOB_RECORD_USER_USAGES_INTERVAL", cast=int, default=15)
# "Online now" window: a user counts as online if their ``online_at`` is within
# this many minutes. The presence tracker polls every core several times per
# window and re-writes the whole window on each tick (see app/presence.py), so
# one minute here is a true "online right now" without losing anyone to a missed
# poll. Raise it only if you want the number to include recently-idle clients.
ONLINE_WINDOW_MINUTES = config("ONLINE_WINDOW_MINUTES", cast=int, default=1)
# Presence tracker: how often each core's per-user traffic counters are polled,
# and the per-core gRPC deadline. The interval is additionally capped at a
# quarter of the online window. It runs on its own thread, so this is
# independent of every job interval.
ONLINE_PRESENCE_INTERVAL = config("ONLINE_PRESENCE_INTERVAL", cast=int, default=15)
ONLINE_PRESENCE_QUERY_TIMEOUT = config("ONLINE_PRESENCE_QUERY_TIMEOUT", cast=int, default=2)
# Fail-closed: after this many blind usage cycles, disconnect all active users on local inbounds.
# 0 disables mass disconnect (logging only). Default 6 cycles ≈ 30s at 5s interval.
BILLING_BLIND_DISCONNECT_CYCLES = config("BILLING_BLIND_DISCONNECT_CYCLES", cast=int, default=6)
# Verified-escalation for the rare case where a non-billable (limited/expired/disabled)
# user keeps transferring on an already-established session after the live handler-API
# remove blocked their new connections. We re-assert the hot remove every usage tick and
# only escalate to a real (batched) core restart — which briefly drops everyone — once a
# user has kept leaking for this many *consecutive* ticks, proving a genuinely abusive
# long-lived session rather than a connection that is merely closing.
# 0 disables the restart escalation entirely (hot remove only; accept a bounded leak).
# Consecutive usage ticks a non-billable user may keep leaking before we
# re-assert per-user hot disable. 0 = never escalate (and never restart the
# core for leaks — default, so quota cuts cannot flap every active account).
LIMITED_LEAK_RESTART_STREAK = config("LIMITED_LEAK_RESTART_STREAK", cast=int, default=0)
JOB_BILL_USAGE_INTERVAL = config("JOB_BILL_USAGE_INTERVAL", cast=int, default=30)

# Usage-based billing (phase 3): minor units charged per GB of user traffic.
# 0 disables the periodic billing job.
USAGE_BILLING_RATE_PER_GB = config("USAGE_BILLING_RATE_PER_GB", cast=int, default=0)
WALLET_LOW_BALANCE_THRESHOLD = config("WALLET_LOW_BALANCE_THRESHOLD", cast=int, default=10000)

# Payment gateways (phase 4). Demo provider is staging-only; opt in explicitly.
PAYMENT_DEMO_ENABLED = config("PAYMENT_DEMO_ENABLED", cast=bool, default=False)
PORTAL_DIRECT_PAYMENT = config("PORTAL_DIRECT_PAYMENT", cast=bool, default=True)
# Pending portal checkouts (no receipt / gateway not completed) auto-expire after this.
PORTAL_PAYMENT_PENDING_TTL_MINUTES = config(
    "PORTAL_PAYMENT_PENDING_TTL_MINUTES", cast=int, default=120
)
# Extra VPN accounts one portal login may own. 0 disables the cap.
PORTAL_MAX_CHILD_ACCOUNTS = config("PORTAL_MAX_CHILD_ACCOUNTS", cast=int, default=20)
PAYMENT_MIN_AMOUNT = config("PAYMENT_MIN_AMOUNT", cast=int, default=100)
PAYMENT_MAX_AMOUNT = config("PAYMENT_MAX_AMOUNT", cast=int, default=100_000_000)

# Sub-reseller limits (phase 5).
SUB_RESELLER_MAX_PER_PARENT = config("SUB_RESELLER_MAX_PER_PARENT", cast=int, default=10)
JOB_REVIEW_USERS_INTERVAL = config("JOB_REVIEW_USERS_INTERVAL", cast=int, default=30)
JOB_SEND_NOTIFICATIONS_INTERVAL = config("JOB_SEND_NOTIFICATIONS_INTERVAL", cast=int, default=30)

# Auto-upgrade Xray-core on panel + Xray nodes when a newer GitHub release exists.
XRAY_AUTO_UPGRADE_ENABLED = config("XRAY_AUTO_UPGRADE_ENABLED", cast=bool, default=True)
XRAY_AUTO_UPGRADE_INTERVAL = config("XRAY_AUTO_UPGRADE_INTERVAL", cast=int, default=21600)
XRAY_AUTO_UPGRADE_INCLUDE_PRERELEASE = config(
    "XRAY_AUTO_UPGRADE_INCLUDE_PRERELEASE", cast=bool, default=False
)
