import os
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship
from sqlalchemy.sql.expression import select, text

from app import xray
from app.db.base import USERNAME_COLLATION, Base
from app.models.node import NodeStatus
from app.models.proxy import (
    ProxyHostALPN,
    ProxyHostFingerprint,
    ProxyHostSecurity,
    ProxyTypes,
)
from app.models.user import ReminderType, UserDataLimitResetStrategy, UserStatus


class Admin(Base):
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True)
    username = Column(String(34), unique=True, index=True)
    hashed_password = Column(String(128))
    users = relationship("User", back_populates="admin")
    created_at = Column(DateTime, default=datetime.utcnow)
    is_sudo = Column(Boolean, default=False)
    password_reset_at = Column(DateTime, nullable=True)
    telegram_id = Column(BigInteger, nullable=True, default=None)
    discord_webhook = Column(String(1024), nullable=True, default=None)
    users_usage = Column(BigInteger, nullable=False, default=0)
    usage_logs = relationship("AdminUsageLogs", back_populates="admin")

    # RBAC / commercial (phase 3). is_sudo stays the source of truth for sudo;
    # `role` refines non-sudo admins. Quotas are null = unlimited.
    role = Column(String(32), nullable=True)
    max_users = Column(Integer, nullable=True)
    max_total_traffic = Column(BigInteger, nullable=True)
    max_nodes = Column(Integer, nullable=True)

    # White-label reseller (phase 6). An admin that belongs to a tenant is a
    # reseller scoped to it; tenant_id NULL means the platform owner.
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    tenant = relationship("Tenant", back_populates="admins", foreign_keys=[tenant_id])


class AdminUsageLogs(Base):
    __tablename__ = "admin_usage_logs"

    id = Column(Integer, primary_key=True)
    admin_id = Column(Integer, ForeignKey("admins.id"))
    admin = relationship("Admin", back_populates="usage_logs")
    used_traffic_at_reset = Column(BigInteger, nullable=False)
    reset_at = Column(DateTime, default=datetime.utcnow)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(
        String(34, collation=USERNAME_COLLATION).with_variant(CITEXT(), "postgresql"),
        unique=True,
        index=True,
    )
    proxies = relationship("Proxy", back_populates="user", cascade="all, delete-orphan")
    status = Column(Enum(UserStatus), nullable=False, default=UserStatus.active, index=True)
    used_traffic = Column(BigInteger, default=0)
    node_usages = relationship("NodeUserUsage", back_populates="user", cascade="all, delete-orphan")
    notification_reminders = relationship("NotificationReminder", back_populates="user", cascade="all, delete-orphan")
    data_limit = Column(BigInteger, nullable=True)
    data_limit_reset_strategy = Column(
        Enum(UserDataLimitResetStrategy),
        nullable=False,
        default=UserDataLimitResetStrategy.no_reset,
    )
    usage_logs = relationship("UserUsageResetLogs", back_populates="user")  # maybe rename it to reset_usage_logs?
    expire = Column(Integer, nullable=True)
    admin_id = Column(Integer, ForeignKey("admins.id"), index=True)
    admin = relationship("Admin", back_populates="users")
    sub_revoked_at = Column(DateTime, nullable=True, default=None)
    sub_updated_at = Column(DateTime, nullable=True, default=None)
    sub_last_user_agent = Column(String(512), nullable=True, default=None)
    created_at = Column(DateTime, default=datetime.utcnow)
    note = Column(String(500), nullable=True, default=None)
    online_at = Column(DateTime, nullable=True, default=None)
    on_hold_expire_duration = Column(BigInteger, nullable=True, default=None)
    on_hold_timeout = Column(DateTime, nullable=True, default=None)

    # * Positive values: User will be deleted after the value of this field in days automatically.
    # * Negative values: User won't be deleted automatically at all.
    # * NULL: Uses global settings.
    auto_delete_in_days = Column(Integer, nullable=True, default=None)

    edit_at = Column(DateTime, nullable=True, default=None)
    last_status_change = Column(DateTime, default=datetime.utcnow, nullable=True)

    next_plan = relationship(
        "NextPlan",
        uselist=False,
        back_populates="user",
        cascade="all, delete-orphan"
    )

    @hybrid_property
    def reseted_usage(self) -> int:
        return int(sum([log.used_traffic_at_reset for log in self.usage_logs]))

    @reseted_usage.expression
    def reseted_usage(cls):
        return (
            select(func.sum(UserUsageResetLogs.used_traffic_at_reset)).
            where(UserUsageResetLogs.user_id == cls.id).
            label('reseted_usage')
        )

    @property
    def lifetime_used_traffic(self) -> int:
        return int(
            sum([log.used_traffic_at_reset for log in self.usage_logs])
            + self.used_traffic
        )

    @property
    def last_traffic_reset_time(self):
        return self.usage_logs[-1].reset_at if self.usage_logs else self.created_at

    @property
    def excluded_inbounds(self):
        _ = {}
        for proxy in self.proxies:
            _[proxy.type] = [i.tag for i in proxy.excluded_inbounds]
        return _

    @property
    def inbounds(self):
        _ = {}
        for proxy in self.proxies:
            _[proxy.type] = []
            excluded_tags = [i.tag for i in proxy.excluded_inbounds]
            for inbound in xray.config.inbounds_by_protocol.get(proxy.type, []):
                if inbound["tag"] not in excluded_tags:
                    _[proxy.type].append(inbound["tag"])

        return _


excluded_inbounds_association = Table(
    "exclude_inbounds_association",
    Base.metadata,
    Column("proxy_id", ForeignKey("proxies.id")),
    Column("inbound_tag", ForeignKey("inbounds.tag")),
)

template_inbounds_association = Table(
    "template_inbounds_association",
    Base.metadata,
    Column("user_template_id", ForeignKey("user_templates.id")),
    Column("inbound_tag", ForeignKey("inbounds.tag")),
)


class NextPlan(Base):
    __tablename__ = 'next_plans'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    data_limit = Column(BigInteger, nullable=False)
    expire = Column(Integer, nullable=True)
    add_remaining_traffic = Column(Boolean, nullable=False, default=False, server_default='0')
    fire_on_either = Column(Boolean, nullable=False, default=True, server_default='0')

    user = relationship("User", back_populates="next_plan")


class UserTemplate(Base):
    __tablename__ = "user_templates"

    id = Column(Integer, primary_key=True)
    name = Column(String(64), nullable=False, unique=True)
    data_limit = Column(BigInteger, default=0)
    expire_duration = Column(BigInteger, default=0)  # in seconds
    username_prefix = Column(String(20), nullable=True)
    username_suffix = Column(String(20), nullable=True)

    inbounds = relationship(
        "ProxyInbound", secondary=template_inbounds_association
    )


class UserUsageResetLogs(Base):
    __tablename__ = "user_usage_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User", back_populates="usage_logs")
    used_traffic_at_reset = Column(BigInteger, nullable=False)
    reset_at = Column(DateTime, default=datetime.utcnow)


class Proxy(Base):
    __tablename__ = "proxies"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User", back_populates="proxies")
    type = Column(Enum(ProxyTypes), nullable=False)
    settings = Column(JSON, nullable=False)
    excluded_inbounds = relationship(
        "ProxyInbound", secondary=excluded_inbounds_association
    )


class ProxyInbound(Base):
    __tablename__ = "inbounds"

    id = Column(Integer, primary_key=True)
    tag = Column(String(256), unique=True, nullable=False, index=True)
    hosts = relationship(
        "ProxyHost", back_populates="inbound", cascade="all, delete-orphan"
    )


class ProxyHost(Base):
    __tablename__ = "hosts"
    # __table_args__ = (
    #     UniqueConstraint('inbound_tag', 'remark'),
    # )

    id = Column(Integer, primary_key=True)
    remark = Column(String(256), unique=False, nullable=False)
    address = Column(String(256), unique=False, nullable=False)
    port = Column(Integer, nullable=True)
    path = Column(String(256), unique=False, nullable=True)
    sni = Column(String(1000), unique=False, nullable=True)
    host = Column(String(1000), unique=False, nullable=True)
    security = Column(
        Enum(ProxyHostSecurity),
        unique=False,
        nullable=False,
        default=ProxyHostSecurity.inbound_default,
    )
    alpn = Column(
        Enum(ProxyHostALPN),
        unique=False,
        nullable=False,
        default=ProxyHostSecurity.none,
        server_default=ProxyHostSecurity.none.name
    )
    fingerprint = Column(
        Enum(ProxyHostFingerprint),
        unique=False,
        nullable=False,
        default=ProxyHostSecurity.none,
        server_default=ProxyHostSecurity.none.name
    )

    inbound_tag = Column(String(256), ForeignKey("inbounds.tag"), nullable=False)
    inbound = relationship("ProxyInbound", back_populates="hosts")
    allowinsecure = Column(Boolean, nullable=True)
    is_disabled = Column(Boolean, nullable=True, default=False)
    mux_enable = Column(Boolean, nullable=False, default=False, server_default='0')
    fragment_setting = Column(String(100), nullable=True)
    noise_setting = Column(String(2000), nullable=True)
    random_user_agent = Column(Boolean, nullable=False, default=False, server_default='0')
    use_sni_as_host = Column(Boolean, nullable=False, default=False, server_default="0")


class System(Base):
    __tablename__ = "system"

    id = Column(Integer, primary_key=True)
    uplink = Column(BigInteger, default=0)
    downlink = Column(BigInteger, default=0)


class JWT(Base):
    __tablename__ = "jwt"

    id = Column(Integer, primary_key=True)
    secret_key = Column(
        String(64), nullable=False, default=lambda: os.urandom(32).hex()
    )


class TLS(Base):
    __tablename__ = "tls"

    id = Column(Integer, primary_key=True)
    key = Column(String(4096), nullable=False)
    certificate = Column(String(2048), nullable=False)


class NodeGroup(Base):
    """A logical grouping of nodes (e.g. by region) for clustering/failover."""

    __tablename__ = "node_groups"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), unique=True, nullable=False)
    region = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    nodes = relationship("Node", back_populates="group")


class Node(Base):
    __tablename__ = "nodes"

    id = Column(Integer, primary_key=True)
    name = Column(
        String(256, collation=USERNAME_COLLATION).with_variant(CITEXT(), "postgresql"),
        unique=True,
    )
    address = Column(String(256), unique=False, nullable=False)
    port = Column(Integer, unique=False, nullable=False)
    api_port = Column(Integer, unique=False, nullable=False)
    xray_version = Column(String(32), nullable=True)
    status = Column(Enum(NodeStatus), nullable=False, default=NodeStatus.connecting)
    last_status_change = Column(DateTime, default=datetime.utcnow)
    message = Column(String(1024), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    uplink = Column(BigInteger, default=0)
    downlink = Column(BigInteger, default=0)
    user_usages = relationship("NodeUserUsage", back_populates="node", cascade="all, delete-orphan")
    usages = relationship("NodeUsage", back_populates="node", cascade="all, delete-orphan")
    usage_coefficient = Column(Float, nullable=False, server_default=text("1.0"), default=1)

    # Which traffic core this node runs: 'xray' (default) or 'wireguard'.
    # Both feed the single central User.used_traffic; the value only selects
    # which agent transport (rpyc Xray vs /wg endpoints) the panel drives.
    core_kind = Column(String(16), nullable=False, server_default=text("'xray'"), default="xray")
    wireguard = relationship(
        "NodeWireGuard",
        back_populates="node",
        uselist=False,
        cascade="all, delete-orphan",
    )

    # Clustering / reliability (phase 2)
    region = Column(String(64), nullable=True, index=True)
    capacity = Column(Integer, nullable=True)
    latency_ms = Column(Float, nullable=True)
    last_health = Column(DateTime, nullable=True)
    group_id = Column(Integer, ForeignKey("node_groups.id"), nullable=True, index=True)
    group = relationship("NodeGroup", back_populates="nodes")

    # White-label / reseller-owned nodes (phase 6). A node provisioned by a
    # reseller belongs to their tenant; usage on it is billed at a discount.
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    owner_admin_id = Column(Integer, ForeignKey("admins.id"), nullable=True, index=True)
    # Topology role: 'direct' (default), 'relay' (in-country bridge), 'exit'.
    role = Column(String(16), nullable=False, server_default=text("'direct'"), default="direct")
    # SSH auto-provisioning bookkeeping (phase 6).
    provision_host = Column(String(256), nullable=True)
    provision_status = Column(String(32), nullable=True)
    provision_message = Column(String(1024), nullable=True)


class NodeWireGuard(Base):
    """Per-node native WireGuard server config (one-to-one with Node).

    Only nodes whose ``core_kind == 'wireguard'`` carry a row here. Keeping it
    in a dedicated table keeps the ``nodes`` table lean and lets non-WG nodes
    have no WG state at all.
    """

    __tablename__ = "node_wireguard"

    node_id = Column(Integer, ForeignKey("nodes.id"), primary_key=True)
    node = relationship("Node", back_populates="wireguard")
    interface = Column(String(32), nullable=False, server_default=text("'wg0'"), default="wg0")
    listen_port = Column(Integer, nullable=False, server_default=text("51820"), default=51820)
    subnet = Column(String(64), nullable=False, server_default=text("'10.10.0.0/24'"), default="10.10.0.0/24")
    private_key = Column(String(64), nullable=False)
    public_key = Column(String(64), nullable=False)
    endpoint = Column(String(256), nullable=True)
    mtu = Column(Integer, nullable=False, server_default=text("1420"), default=1420)
    dns = Column(String(256), nullable=True)


class NodeUserUsage(Base):
    __tablename__ = "node_user_usages"
    __table_args__ = (
        UniqueConstraint('created_at', 'user_id', 'node_id'),
    )

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, unique=False, nullable=False)  # one hour per record
    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User", back_populates="node_usages")
    node_id = Column(Integer, ForeignKey("nodes.id"))
    node = relationship("Node", back_populates="user_usages")
    used_traffic = Column(BigInteger, default=0)


class NodeUsage(Base):
    __tablename__ = "node_usages"
    __table_args__ = (
        UniqueConstraint('created_at', 'node_id'),
    )

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, unique=False, nullable=False)  # one hour per record
    node_id = Column(Integer, ForeignKey("nodes.id"))
    node = relationship("Node", back_populates="usages")
    uplink = Column(BigInteger, default=0)
    downlink = Column(BigInteger, default=0)


class NotificationReminder(Base):
    __tablename__ = "notification_reminders"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User", back_populates="notification_reminders")
    type = Column(Enum(ReminderType), nullable=False)
    threshold = Column(Integer, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Event(Base):
    """Durable audit log of events published on the event bus."""

    __tablename__ = "events"

    id = Column(Integer, primary_key=True)
    type = Column(String(64), nullable=False, index=True)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class FeatureFlag(Base):
    """Toggle for gating features and gradual rollout.

    A row with ``admin_id = NULL`` is the global value for a flag; a row with an
    ``admin_id`` overrides the flag for that admin only.
    """

    __tablename__ = "feature_flags"
    __table_args__ = (
        UniqueConstraint('name', 'admin_id', name='uq_feature_flag_name_admin'),
    )

    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False, index=True)
    enabled = Column(Boolean, nullable=False, default=False)
    admin_id = Column(Integer, ForeignKey("admins.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Rule(Base):
    """Automation rule: when ``trigger_event`` fires and ``condition`` matches,
    run ``action`` with ``action_params``."""

    __tablename__ = "rules"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    trigger_event = Column(String(64), nullable=False, index=True)
    condition = Column(JSON, nullable=True)
    action = Column(String(64), nullable=False)
    action_params = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MarketplacePlugin(Base):
    """A plugin in the marketplace catalogue and its install state."""

    __tablename__ = "marketplace_plugins"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), unique=True, nullable=False, index=True)
    version = Column(String(32), nullable=True)
    description = Column(String(1024), nullable=True)
    author = Column(String(128), nullable=True)
    source_url = Column(String(512), nullable=True)
    installed = Column(Boolean, nullable=False, default=False)
    enabled = Column(Boolean, nullable=False, default=False)
    rating_sum = Column(Integer, nullable=False, default=0)
    rating_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    reviews = relationship("PluginReview", back_populates="plugin", cascade="all, delete-orphan")


class PluginReview(Base):
    """A rating (1-5) and optional comment left by an admin on a plugin."""

    __tablename__ = "plugin_reviews"
    __table_args__ = (
        UniqueConstraint("plugin_id", "admin_id", name="uq_plugin_review_admin"),
    )

    id = Column(Integer, primary_key=True)
    plugin_id = Column(Integer, ForeignKey("marketplace_plugins.id"), nullable=False, index=True)
    admin_id = Column(Integer, ForeignKey("admins.id"), nullable=True)
    rating = Column(Integer, nullable=False)
    comment = Column(String(1024), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    plugin = relationship("MarketplacePlugin", back_populates="reviews")


class Workflow(Base):
    """A multi-step automation: when ``trigger_event`` fires and ``condition``
    matches, run ``steps`` (an ordered list of ``{action, params}``) in sequence.
    Builds on the rule-engine action registry (phase 4)."""

    __tablename__ = "workflows"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    trigger_event = Column(String(64), nullable=False, index=True)
    condition = Column(JSON, nullable=True)
    steps = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Plan(Base):
    """A commercial plan/policy: pricing and the limits applied to a user."""

    __tablename__ = "plans"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), unique=True, nullable=False)
    price = Column(BigInteger, nullable=False, default=0)        # minor units (e.g. cents)
    data_limit = Column(BigInteger, nullable=True)               # bytes; null = unlimited
    duration_days = Column(Integer, nullable=True)               # null = no expiry
    device_limit = Column(Integer, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Wallet(Base):
    """Per-admin (reseller/customer) prepaid balance."""

    __tablename__ = "wallets"

    id = Column(Integer, primary_key=True)
    admin_id = Column(Integer, ForeignKey("admins.id"), unique=True, nullable=False)
    balance = Column(BigInteger, nullable=False, default=0)      # minor units
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    admin = relationship("Admin")


class Transaction(Base):
    """An immutable ledger entry against a wallet."""

    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True)
    admin_id = Column(Integer, ForeignKey("admins.id"), index=True, nullable=False)
    amount = Column(BigInteger, nullable=False)                  # signed minor units
    type = Column(String(32), nullable=False)                   # credit|debit|invoice|refund
    description = Column(String(512), nullable=True)
    reference = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class Invoice(Base):
    """A billable charge, optionally tied to a plan."""

    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True)
    admin_id = Column(Integer, ForeignKey("admins.id"), index=True, nullable=False)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=True)
    amount = Column(BigInteger, nullable=False)                 # minor units
    status = Column(String(16), nullable=False, default="pending", index=True)  # pending|paid|canceled
    provider = Column(String(32), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    paid_at = Column(DateTime, nullable=True)


class ApiKey(Base):
    """A hashed API key for the developer platform (v2 API)."""

    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True)
    admin_id = Column(Integer, ForeignKey("admins.id"), index=True, nullable=False)
    name = Column(String(128), nullable=False)
    prefix = Column(String(16), index=True, nullable=False)
    key_hash = Column(String(128), unique=True, nullable=False)
    scopes = Column(JSON, nullable=True)
    revoked = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)


class Tenant(Base):
    """A white-label reseller workspace living inside a single panel install.

    A tenant scopes admins, users, plans and nodes so a reseller can run their
    own brand without a separate server (phase 6). ``owner_admin_id`` is the
    reseller admin that owns this tenant.
    """

    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True)
    slug = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(128), nullable=False)
    owner_admin_id = Column(Integer, ForeignKey("admins.id"), nullable=True, index=True)
    enabled = Column(Boolean, nullable=False, default=True)

    # Reseller limits (null = unlimited).
    max_users = Column(Integer, nullable=True)
    max_nodes = Column(Integer, nullable=True)

    # "Bring your own node" discount: percentage (0-100) shaved off the owner's
    # usage rate for traffic served on this tenant's own provisioned nodes.
    byo_node_discount_percent = Column(Integer, nullable=False, default=0, server_default=text("0"))

    created_at = Column(DateTime, default=datetime.utcnow)

    admins = relationship("Admin", back_populates="tenant", foreign_keys="Admin.tenant_id")
    branding = relationship(
        "BrandingSettings",
        back_populates="tenant",
        uselist=False,
        cascade="all, delete-orphan",
    )


class BrandingSettings(Base):
    """Per-tenant white-label appearance (logo, colours, titles, support link).

    A row with ``tenant_id = NULL`` is the platform-wide default brand.
    """

    __tablename__ = "branding_settings"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_branding_tenant"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    panel_title = Column(String(128), nullable=True)
    logo_url = Column(String(512), nullable=True)
    favicon_url = Column(String(512), nullable=True)
    primary_color = Column(String(16), nullable=True)
    support_url = Column(String(512), nullable=True)
    sub_profile_title = Column(String(128), nullable=True)
    domain = Column(String(256), nullable=True, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="branding")


class Tunnel(Base):
    """An encrypted hop between an in-country ``relay`` node and a foreign
    ``exit`` node (phase 6). Many protocols don't survive a direct connection
    from inside Iran, so clients hit the relay which forwards to the exit over a
    secure transport. The panel generates the relay outbound and exit inbound
    Xray fragments from this definition.
    """

    __tablename__ = "tunnels"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    relay_node_id = Column(Integer, ForeignKey("nodes.id"), nullable=False, index=True)
    exit_node_id = Column(Integer, ForeignKey("nodes.id"), nullable=False, index=True)
    # Transport for the relay->exit hop: 'reality' | 'ws' | 'grpc' | 'tcp'.
    transport = Column(String(16), nullable=False, default="reality")
    listen_port = Column(Integer, nullable=False)        # port clients hit on the relay
    target_port = Column(Integer, nullable=False)        # port the exit listens on
    params = Column(JSON, nullable=True)                 # transport-specific (sni, path, keys...)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    relay_node = relationship("Node", foreign_keys=[relay_node_id])
    exit_node = relationship("Node", foreign_keys=[exit_node_id])
