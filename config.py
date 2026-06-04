from decouple import config
from dotenv import load_dotenv

load_dotenv()


SQLALCHEMY_DATABASE_URL = config("SQLALCHEMY_DATABASE_URL", default="sqlite:///db.sqlite3")
SQLALCHEMY_POOL_SIZE = config("SQLALCHEMY_POOL_SIZE", cast=int, default=10)
SQLIALCHEMY_MAX_OVERFLOW = config("SQLIALCHEMY_MAX_OVERFLOW", cast=int, default=30)

# Optional Redis URL used by the event bus / cache layer. When empty, the panel
# falls back to an in-process backend (single-instance only). Required for HA.
REDIS_URL = config("REDIS_URL", default="")

# How long to keep persisted events in the audit log. Set <= 0 to disable
# automatic cleanup (keep forever).
EVENTS_RETENTION_DAYS = config("EVENTS_RETENTION_DAYS", cast=int, default=30)

# Emit logs as structured JSON (useful for log aggregation / observability).
LOG_JSON = config("LOG_JSON", cast=bool, default=False)

# Optional static token for scraping the Prometheus /api/metrics endpoint.
# When set, a request with header `Authorization: Bearer <token>` (or `?token=`)
# is accepted without an admin session. When empty, a sudo admin token is required.
METRICS_TOKEN = config("METRICS_TOKEN", default="")

# Cluster / reliability
# Token allowing a node to self-register via POST /api/node/bootstrap.
# Leave empty to disable auto-discovery.
NODE_BOOTSTRAP_TOKEN = config("NODE_BOOTSTRAP_TOKEN", default="")
# Shared secret for REST node control API (header X-Nexus-Control-Secret). Empty = disabled.
NODE_CONTROL_SECRET = config("NODE_CONTROL_SECRET", default="")
# When True, panel verifies node agent TLS certificates (requires valid certs on nodes).
NODE_SSL_VERIFY = config("NODE_SSL_VERIFY", cast=bool, default=False)
NODE_BOOTSTRAP_MAX_ATTEMPTS = config("NODE_BOOTSTRAP_MAX_ATTEMPTS", cast=int, default=20)
NODE_BOOTSTRAP_WINDOW_SECONDS = config("NODE_BOOTSTRAP_WINDOW_SECONDS", cast=int, default=3600)
LOGIN_MAX_ATTEMPTS = config("LOGIN_MAX_ATTEMPTS", cast=int, default=10)
LOGIN_MAX_WINDOW_SECONDS = config("LOGIN_MAX_WINDOW_SECONDS", cast=int, default=900)
PROVISIONING_SSH_STRICT_HOST_KEY = config("PROVISIONING_SSH_STRICT_HOST_KEY", cast=bool, default=True)
# Interval (seconds) for the cluster failover detector. 0 disables it.
CLUSTER_FAILOVER_CHECK_INTERVAL = config("CLUSTER_FAILOVER_CHECK_INTERVAL", cast=int, default=0)
# A node must stay in error for this many seconds before being considered down.
CLUSTER_NODE_DOWN_SECONDS = config("CLUSTER_NODE_DOWN_SECONDS", cast=int, default=180)
# Automatically disable a persistently-down node (failover). Off by default.
CLUSTER_AUTO_DISABLE_DOWN_NODES = config("CLUSTER_AUTO_DISABLE_DOWN_NODES", cast=bool, default=False)

# OpenTelemetry tracing
OTEL_ENABLED = config("OTEL_ENABLED", cast=bool, default=False)
OTEL_EXPORTER_OTLP_ENDPOINT = config("OTEL_EXPORTER_OTLP_ENDPOINT", default="http://127.0.0.1:4317")
OTEL_SERVICE_NAME = config("OTEL_SERVICE_NAME", default="nexuspanel")

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
NODE_AGENT_IMAGE = config("NODE_AGENT_IMAGE", default="nexuspanel/node:latest")
# SSH connect timeout (seconds) when auto-provisioning a node.
NODE_PROVISION_SSH_TIMEOUT = config("NODE_PROVISION_SSH_TIMEOUT", cast=int, default=20)
# Default ports a provisioned node listens on.
NODE_DEFAULT_PORT = config("NODE_DEFAULT_PORT", cast=int, default=62050)
NODE_DEFAULT_API_PORT = config("NODE_DEFAULT_API_PORT", cast=int, default=62051)

# Backup & disaster recovery
BACKUP_DIR = config("BACKUP_DIR", default="/var/lib/nexuspanel/backups")
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
XRAY_FALLBACKS_INBOUND_TAG = config("XRAY_FALLBACKS_INBOUND_TAG", cast=str, default="") or config(
    "XRAY_FALLBACK_INBOUND_TAG", cast=str, default=""
)
XRAY_EXECUTABLE_PATH = config("XRAY_EXECUTABLE_PATH", default="/usr/local/bin/xray")
XRAY_ASSETS_PATH = config("XRAY_ASSETS_PATH", default="/usr/local/share/xray")
XRAY_EXCLUDE_INBOUND_TAGS = config("XRAY_EXCLUDE_INBOUND_TAGS", default='').split()
XRAY_SUBSCRIPTION_URL_PREFIX = config("XRAY_SUBSCRIPTION_URL_PREFIX", default="").strip("/")
XRAY_SUBSCRIPTION_PATH = config("XRAY_SUBSCRIPTION_PATH", default="sub").strip("/")

TELEGRAM_API_TOKEN = config("TELEGRAM_API_TOKEN", default="")
TELEGRAM_ADMIN_ID = config(
    'TELEGRAM_ADMIN_ID',
    default="",
    cast=lambda v: [int(i) for i in filter(str.isdigit, (s.strip() for s in v.split(',')))]
)
TELEGRAM_PROXY_URL = config("TELEGRAM_PROXY_URL", default="")
TELEGRAM_LOGGER_CHANNEL_ID = config("TELEGRAM_LOGGER_CHANNEL_ID", cast=int, default=0)
TELEGRAM_DEFAULT_VLESS_FLOW = config("TELEGRAM_DEFAULT_VLESS_FLOW", default="")

JWT_ACCESS_TOKEN_EXPIRE_MINUTES = config("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", cast=int, default=1440)

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
    logging.getLogger("nexuspanel.config").warning(
        "SUDO_PASSWORD is ignored when SUDO_PASSWORD_HASH is set"
    )
elif SUDO_PASSWORD and not SUDO_PASSWORD_HASH:
    import logging
    logging.getLogger("nexuspanel.config").warning(
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
SUB_PROFILE_TITLE = config("SUB_PROFILE_TITLE", default="Subscription")

# discord webhook log
DISCORD_WEBHOOK_URL = config("DISCORD_WEBHOOK_URL", default="")


# Interval jobs, all values are in seconds
JOB_CORE_HEALTH_CHECK_INTERVAL = config("JOB_CORE_HEALTH_CHECK_INTERVAL", cast=int, default=10)
JOB_RECORD_NODE_USAGES_INTERVAL = config("JOB_RECORD_NODE_USAGES_INTERVAL", cast=int, default=30)
JOB_RECORD_USER_USAGES_INTERVAL = config("JOB_RECORD_USER_USAGES_INTERVAL", cast=int, default=10)
JOB_REVIEW_USERS_INTERVAL = config("JOB_REVIEW_USERS_INTERVAL", cast=int, default=10)
JOB_SEND_NOTIFICATIONS_INTERVAL = config("JOB_SEND_NOTIFICATIONS_INTERVAL", cast=int, default=30)
