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
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import backref, relationship
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
    # Base32 TOTP secret for optional admin 2FA. NULL = 2FA disabled for this
    # admin (login behaves exactly as before). Opt-in per admin.
    totp_secret = Column(String(64), nullable=True, default=None)
    telegram_id = Column(BigInteger, nullable=True, default=None)
    discord_webhook = Column(String(1024), nullable=True, default=None)
    users_usage = Column(BigInteger, nullable=False, default=0)
    usage_logs = relationship("AdminUsageLogs", back_populates="admin")

    # RBAC / commercial (phase 3). is_sudo stays the source of truth for sudo;
    # `role` refines non-sudo admins. Quotas are null = unlimited.
    role = Column(String(32), nullable=True)
    max_users = Column(Integer, nullable=True)
    max_total_traffic = Column(BigInteger, nullable=True)
    # Prepaid GB pool from traffic packages (consumed before wallet pay-as-you-go).
    prepaid_traffic_remaining = Column(BigInteger, nullable=False, default=0, server_default=text("0"))
    # Optional PAYG override (minor units / GB). NULL = platform billing.usage_rate_per_gb.
    usage_rate_per_gb = Column(BigInteger, nullable=True, default=None)
    max_nodes = Column(Integer, nullable=True)

    # White-label reseller (phase 6). An admin that belongs to a tenant is a
    # reseller scoped to it; tenant_id NULL means the platform owner.
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    tenant = relationship("Tenant", back_populates="admins", foreign_keys=[tenant_id])

    # Sub-reseller hierarchy (phase 5). A child reseller is managed by parent_admin.
    parent_admin_id = Column(Integer, ForeignKey("admins.id"), nullable=True, index=True)
    parent = relationship("Admin", remote_side=[id], foreign_keys=[parent_admin_id])
    # Commission (phase 6): % of child spend credited to parent_admin.
    commission_percent = Column(Integer, nullable=False, default=0, server_default=text("0"))
    # Opt-in: reseller's portal customers / top-up may use platform CentralPay.
    centralpay_enabled = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    # Per-reseller card-to-card (never inherits master's platform card).
    card_enabled = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    card_number = Column(String(64), nullable=True)
    card_holder = Column(String(128), nullable=True)
    card_bank = Column(String(128), nullable=True)
    # Multiple cards: [{id, number, holder, bank, enabled?}]. Scalars kept as legacy mirror of first card.
    cards = Column(JSON, nullable=True)

    # Public storefront / acquisition (landing + signup + invite).
    invite_code = Column(String(32), unique=True, nullable=True, index=True)
    public_signup_enabled = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    reseller_apply_enabled = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    storefront_headline = Column(String(256), nullable=True)
    storefront_tagline = Column(String(512), nullable=True)



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
    wg_peer = relationship("WgPeer", back_populates="user", uselist=False, cascade="all, delete-orphan")
    status = Column(Enum(UserStatus), nullable=False, default=UserStatus.active, index=True)
    used_traffic = Column(BigInteger, default=0)
    # Bytes consumed after the plan quota was exhausted (limited/expired/etc.).
    # Shown to admins/users; applied to used_traffic when the account is recharged.
    overage_traffic = Column(BigInteger, nullable=False, server_default=text("0"), default=0)
    # Informational upload/download split. NEVER used for quota enforcement —
    # quota always uses the single authoritative ``used_traffic`` (up+down).
    # Populated best-effort by the usage recorder so subscription clients that
    # display upload/download separately (v2rayN, Nekoray, ...) show real data.
    used_traffic_up = Column(BigInteger, nullable=False, server_default=text("0"), default=0)
    used_traffic_down = Column(BigInteger, nullable=False, server_default=text("0"), default=0)
    node_usages = relationship("NodeUserUsage", back_populates="user", cascade="all, delete-orphan")
    notification_reminders = relationship("NotificationReminder", back_populates="user", cascade="all, delete-orphan")
    data_limit = Column(BigInteger, nullable=True)
    data_limit_reset_strategy = Column(
        Enum(UserDataLimitResetStrategy),
        nullable=False,
        default=UserDataLimitResetStrategy.no_reset,
    )
    usage_logs = relationship("UserUsageResetLogs", back_populates="user")  # maybe rename it to reset_usage_logs?
    expire = Column(Integer, nullable=True, index=True)
    admin_id = Column(Integer, ForeignKey("admins.id"), index=True)
    admin = relationship("Admin", back_populates="users")
    sub_token = Column(String(32), unique=True, nullable=True, index=True)
    sub_revoked_at = Column(DateTime, nullable=True, default=None)
    sub_updated_at = Column(DateTime, nullable=True, default=None)
    sub_last_user_agent = Column(String(512), nullable=True, default=None)
    created_at = Column(DateTime, default=datetime.utcnow)
    note = Column(String(500), nullable=True, default=None)
    online_at = Column(DateTime, nullable=True, default=None)
    on_hold_expire_duration = Column(BigInteger, nullable=True, default=None)
    on_hold_timeout = Column(DateTime, nullable=True, default=None)

    # Concurrent device cap (distinct client IPs within 24h). Copied from Plan
    # on apply; NULL/0 = unlimited.
    device_limit = Column(Integer, nullable=True, default=None)
    device_ips = Column(Text, nullable=True, default=None)
    # Live 1-device exclusivity: temporarily hold other protocol families while
    # one winner (wireguard / xray / singbox) is online. See device_exclusivity.
    device_conn_hold = Column(JSON, nullable=True, default=None)
    # Per-user speed limits stored in Mbps (UI unit). Xray policy converts to bytes/sec.
    speed_limit_up = Column(BigInteger, nullable=True, default=None)
    speed_limit_down = Column(BigInteger, nullable=True, default=None)
    # Max continuous online session length (minutes). NULL/0 = unlimited.
    session_limit_minutes = Column(Integer, nullable=True, default=None)
    routing_preset = Column(String(64), nullable=True)
    dns_policy = Column(JSON, nullable=True)
    # Portal Family Guard (parental controls): schedules, adult/service/domain blocks.
    family_controls = Column(JSON, nullable=True)

    # * Positive values: User will be deleted after the value of this field in days automatically.
    # * Negative values: User won't be deleted automatically at all.
    # * NULL: Uses global settings.
    auto_delete_in_days = Column(Integer, nullable=True, default=None)

    edit_at = Column(DateTime, nullable=True, default=None)
    last_status_change = Column(DateTime, default=datetime.utcnow, nullable=True)

    portal_enabled = Column(Boolean, nullable=False, default=False)
    hashed_portal_password = Column(String(128), nullable=True)
    portal_password_reset_at = Column(DateTime, nullable=True)
    # First portal login must change VPN username + portal password.
    must_change_credentials = Column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    # Unread push count for installed portal PWA home-screen badge.
    portal_unread = Column(Integer, nullable=False, server_default=text("0"), default=0)
    # Payment intent ids the portal user has opened (message-style read receipts).
    portal_tx_reads = Column(JSON, nullable=True)
    # Portal login user that owns this VPN account (self-service multi-account).
    # NULL = this row is a portal login (or legacy standalone account).
    portal_owner_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # True when the user was auto-disabled because its owning reseller exceeded
    # its ``max_total_traffic`` cap (phase 3). Only these users are auto-
    # reactivated when the reseller drops back under the cap, so a reseller's
    # own manual disables are never silently re-enabled.
    capped_by_reseller = Column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )

    # Last wholesale tariff debited for this account (anti create-then-edit bypass).
    reseller_tariff_charged_id = Column(
        Integer,
        ForeignKey("reseller_plan_tariffs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Expire timestamp that was covered by that charge (renew if new expire exceeds it).
    reseller_tariff_charged_expire = Column(Integer, nullable=True)

    # SigmaGuard client profile (phase A): 'gamer' | 'trader' | 'normal'.
    # Drives protocol priority and node-selection policy in the client API.
    client_profile = Column(
        String(16), nullable=False, server_default=text("'normal'"), default="normal"
    )

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
        from app.xray.inbound_match import inbound_matches_proxy

        _ = {}
        for proxy in self.proxies:
            _[proxy.type] = []
            excluded_tags = [i.tag for i in proxy.excluded_inbounds]
            for inbound in xray.config.product_inbounds_for_type(proxy.type):
                tag = inbound["tag"]
                if tag in excluded_tags:
                    continue
                if not inbound_matches_proxy(proxy.type, tag, proxy.settings, inbound_meta=inbound):
                    continue
                _[proxy.type].append(tag)

        return _


excluded_inbounds_association = Table(
    "exclude_inbounds_association",
    Base.metadata,
    Column("proxy_id", ForeignKey("proxies.id"), index=True),
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
    data_limit_reset_strategy = Column(
        Enum(UserDataLimitResetStrategy),
        nullable=True,
    )
    default_status = Column(Enum(UserStatus), nullable=True)
    note = Column(String(500), nullable=True)
    next_plan = Column(JSON, nullable=True)

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
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    user = relationship("User", back_populates="proxies")
    type = Column(Enum(ProxyTypes), nullable=False, index=True)
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
        Enum(ProxyHostALPN, name="alpn", create_type=False),
        unique=False,
        nullable=False,
        default=ProxyHostALPN.none,
        server_default="none",
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
    sort_order = Column(Integer, nullable=False, default=0, server_default="0")
    override_sni_from_address = Column(Boolean, nullable=False, default=False, server_default="0")
    keep_sni_blank = Column(Boolean, nullable=False, default=False, server_default="0")
    pinned_peer_cert_sha256 = Column(Text, nullable=True)
    verify_peer_cert_by_name = Column(String(256), nullable=True)
    ech_config_list = Column(Text, nullable=True)
    mux_params = Column(Text, nullable=True)
    sockopt_params = Column(Text, nullable=True)
    final_mask = Column(Text, nullable=True)
    vless_route = Column(String(16), nullable=True)
    exclude_from_sub_types = Column(Text, nullable=True)
    mihomo_ip_version = Column(String(32), nullable=True)
    external_proxy = Column(Text, nullable=True)
    node_ids = Column(Text, nullable=True)
    region = Column(String(64), nullable=True)


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
    # Pinned SHA-256 fingerprint of the node's TLS server cert. Captured on the
    # first successful connection (trust-on-first-use) and verified on every
    # later connection, giving secure panel->node mTLS even with self-signed
    # certs (no CA required). NULL = not yet pinned.
    server_cert_sha256 = Column(String(64), nullable=True, default=None)
    # Optional JSON merge-patch applied to this node's effective Xray config
    # (outbounds/routing/inbounds fragments) after master filter + tunnels.
    xray_config_override = Column(Text, nullable=True, default=None)
    # Per-node Cloudflare WARP exit (independent of master routing).
    # When enabled, build_node_xray_config injects the WARP outbound for
    # ``warp_tag`` (default ``warp``) and sets catch-all routing to it.
    # When disabled, inherited master WARP outbounds/rules are stripped to DIRECT.
    warp_enabled = Column(Boolean, nullable=False, server_default=text("false"), default=False)
    warp_tag = Column(String(64), nullable=True, default=None)
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
    wg_interfaces = relationship(
        "WgInterface",
        back_populates="node",
        cascade="all, delete-orphan",
    )
    singbox = relationship(
        "NodeSingBox",
        back_populates="node",
        uselist=False,
        cascade="all, delete-orphan",
    )
    service_bindings = relationship(
        "NodeServiceBinding",
        back_populates="node",
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
    subnet = Column(String(64), nullable=False, server_default=text("'10.10.0.0/16'"), default="10.10.0.0/16")
    # Historical gateway host (no prefix). Pinned before auto-widen so a
    # non-aligned supernet cannot move the interface Address or free that IP
    # for peer allocation.
    interface_host = Column(String(64), nullable=True)
    private_key = Column(String(64), nullable=False)
    public_key = Column(String(64), nullable=False)
    endpoint = Column(String(256), nullable=True)
    mtu = Column(Integer, nullable=False, server_default=text("1420"), default=1420)
    dns = Column(String(256), nullable=True)
    plain_enabled = Column(Boolean, nullable=False, server_default=text("1"), default=True)

    # Dual-stack AmneziaWG listener (separate interface + port from plain WG).
    awg_enabled = Column(Boolean, nullable=False, server_default=text("0"), default=False)
    awg_interface = Column(String(32), nullable=False, server_default=text("'wg1'"), default="wg1")
    awg_listen_port = Column(Integer, nullable=False, server_default=text("51821"), default=51821)
    awg_subnet = Column(String(64), nullable=False, server_default=text("'10.11.0.0/16'"), default="10.11.0.0/16")
    awg_interface_host = Column(String(64), nullable=True)
    awg_private_key = Column(String(64), nullable=True)
    awg_public_key = Column(String(64), nullable=True)
    awg_endpoint = Column(String(256), nullable=True)

    # AmneziaWG obfuscation parameters. Used on the awg_interface listener when
    # awg_enabled is true. Jc/Jmin/Jmax are junk-packet
    # counts/sizes; S1/S2 are init/response junk sizes; H1–H4 are magic headers.
    awg_jc = Column(Integer, nullable=True)
    awg_jmin = Column(Integer, nullable=True)
    awg_jmax = Column(Integer, nullable=True)
    awg_s1 = Column(Integer, nullable=True)
    awg_s2 = Column(Integer, nullable=True)
    awg_h1 = Column(BigInteger, nullable=True)
    awg_h2 = Column(BigInteger, nullable=True)
    awg_h3 = Column(BigInteger, nullable=True)
    awg_h4 = Column(BigInteger, nullable=True)
    awg_s3 = Column(Integer, nullable=True)
    awg_s4 = Column(Integer, nullable=True)

    # SigmaGuard Wire: proprietary preset synced to awg listener (not public AWG).
    sg_wire_enabled = Column(Boolean, nullable=False, server_default=text("0"), default=False)
    sg_wire_preset_rev = Column(String(32), nullable=True)

    # Optional third listener: a plain, unobfuscated WireGuard socket that stays
    # up on relay nodes even when ``interface``/``listen_port`` is delegated to
    # the Xray tunnel. Same identity (private_key/public_key/subnet/peers) as
    # the plain listener — just a second UDP port any stock WireGuard client
    # can dial directly, so tunnel and direct paths can be offered side by
    # side without a port conflict. Null/unset disables the feature.
    direct_listen_port = Column(Integer, nullable=True)

    # Xray-core's *native* userspace WireGuard inbound (wireguard-go + gVisor),
    # not a kernel interface at all — Xray itself terminates the WG protocol
    # and dispatches decrypted traffic through its own routing. Layered with
    # Finalmask "noise" streamSettings, this hides the WireGuard handshake
    # signature from DPI (the same technique 3x-ui exposes). Trade-off: only
    # Xray-core-based clients understand Finalmask, not stock WireGuard apps.
    # Reuses this row's private_key/public_key as the server identity so the
    # same client keypair works across every WG transport this node offers.
    xray_wg_enabled = Column(Boolean, nullable=False, server_default=text("0"), default=False)
    xray_wg_listen_port = Column(Integer, nullable=True)
    xray_wg_mtu = Column(Integer, nullable=False, server_default=text("1420"), default=1420)
    # JSONB on Postgres (not JSON): callers like crud.get_wireguard_nodes() run
    # .distinct() on this row's whole column set, and Postgres' plain `json`
    # type has no equality operator (breaks with "could not identify an
    # equality operator for type json"). jsonb has one. Falls back to plain
    # JSON on other dialects (e.g. sqlite in tests), which has no such issue.
    xray_wg_noise = Column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)


class NodeSingBox(Base):
    """Per-node sing-box server config for the QUIC product protocols
    (Hysteria2 / TUIC), one-to-one with Node.

    A node carries a row here only when the operator enables one of these
    protocols on it. Both inbounds share the node's TLS material and a local
    Clash API port the panel polls for per-user traffic.
    """

    __tablename__ = "node_singbox"

    node_id = Column(Integer, ForeignKey("nodes.id"), primary_key=True)
    node = relationship("Node", back_populates="singbox")

    # Shared TLS material (paths on the node) + the public SNI/host clients use.
    certificate_path = Column(String(512), nullable=True)
    key_path = Column(String(512), nullable=True)
    sni = Column(String(256), nullable=True)
    # Let's Encrypt bookkeeping — set after a successful ACME issue/renew.
    tls_trusted = Column(Boolean, nullable=False, server_default=text("0"), default=False)
    tls_issuer = Column(String(256), nullable=True)
    tls_expires_at = Column(DateTime, nullable=True)
    tls_le_domain = Column(String(256), nullable=True)
    tls_le_kind = Column(String(16), nullable=True)  # domain | ip
    # Local Clash API the panel polls for per-user traffic counters.
    clash_api_port = Column(Integer, nullable=False, server_default=text("9095"), default=9095)
    clash_api_secret = Column(String(128), nullable=True)

    # Hysteria2 inbound
    hysteria2_enabled = Column(Boolean, nullable=False, server_default=text("0"), default=False)
    hysteria2_port = Column(Integer, nullable=True)
    hysteria2_up_mbps = Column(Integer, nullable=True)
    hysteria2_down_mbps = Column(Integer, nullable=True)
    hysteria2_obfs_password = Column(String(128), nullable=True)

    # TUIC inbound
    tuic_enabled = Column(Boolean, nullable=False, server_default=text("0"), default=False)
    tuic_port = Column(Integer, nullable=True)
    tuic_congestion_control = Column(String(16), nullable=False, server_default=text("'bbr'"), default="bbr")

    # AnyTLS inbound (TCP/TLS via sing-box)
    anytls_enabled = Column(Boolean, nullable=False, server_default=text("0"), default=False)
    anytls_port = Column(Integer, nullable=True)


class PanelService(Base):
    """Master service catalog — define each protocol once."""

    __tablename__ = "panel_services"

    slug = Column(String(64), primary_key=True)
    display_name = Column(String(128), nullable=False)
    engine = Column(String(16), nullable=False)  # xray | wireguard | singbox
    protocol = Column(String(32), nullable=False)
    config = Column(JSON, nullable=False, default=dict)
    is_active = Column(Boolean, nullable=False, server_default=text("1"), default=True)
    sort_order = Column(Integer, nullable=False, server_default=text("0"), default=0)


class NodeServiceBinding(Base):
    """Which catalog services are enabled on a node."""

    __tablename__ = "node_service_bindings"
    __table_args__ = (UniqueConstraint("node_id", "service_slug"),)

    id = Column(Integer, primary_key=True)
    node_id = Column(Integer, ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    service_slug = Column(String(64), ForeignKey("panel_services.slug"), nullable=False)
    enabled = Column(Boolean, nullable=False, server_default=text("1"), default=True)
    overrides = Column(JSON, nullable=True)
    node = relationship("Node", back_populates="service_bindings")
    service = relationship("PanelService")


class NodeUserUsage(Base):
    __tablename__ = "node_user_usages"
    __table_args__ = (
        UniqueConstraint('created_at', 'user_id', 'node_id'),
    )

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, unique=False, nullable=False)  # one hour per record
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    user = relationship("User", back_populates="node_usages")
    node_id = Column(Integer, ForeignKey("nodes.id"))
    node = relationship("Node", back_populates="user_usages")
    used_traffic = Column(BigInteger, default=0)


class NodeUserProtocolUsage(Base):
    """Hourly per-user traffic split by protocol (informational analytics)."""

    __tablename__ = "node_user_protocol_usages"
    __table_args__ = (
        UniqueConstraint("created_at", "user_id", "node_id", "protocol", name="uq_proto_usage_hour"),
    )

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    node_id = Column(Integer, ForeignKey("nodes.id"), nullable=True, index=True)
    protocol = Column(String(32), nullable=False, index=True)
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
    name = Column(String(128), nullable=False)
    price = Column(BigInteger, nullable=False, default=0)        # minor units (e.g. cents)
    data_limit = Column(BigInteger, nullable=True)               # bytes; null = unlimited
    duration_days = Column(Integer, nullable=True)               # null = no expiry
    device_limit = Column(Integer, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    owner_admin_id = Column(Integer, ForeignKey("admins.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ResellerTrafficPackage(Base):
    """Master catalog of prepaid traffic packs resellers can buy with wallet."""

    __tablename__ = "reseller_traffic_packages"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False)
    bytes = Column(BigInteger, nullable=False)                   # traffic granted
    price = Column(BigInteger, nullable=False, default=0)        # minor units
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ResellerPlanTariff(Base):
    """Wholesale tariffs for resellers — separate from master retail Plans.

    Sudo defines these under Resellers → Tariffs. When a reseller creates an
    account or their customer buys/renews a matching commercial plan, this
    ``price`` is debited from the reseller wallet. ``data_limit`` null/0 =
    unlimited; otherwise volume in bytes. Never shown in the customer portal.

    ``device_limit`` / ``speed_limit_*`` (Mbps) when set are forced onto
    reseller-created accounts and cannot be changed by the reseller.
    """

    __tablename__ = "reseller_plan_tariffs"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False)
    price = Column(BigInteger, nullable=False, default=0)
    data_limit = Column(BigInteger, nullable=True)   # null/0 = unlimited
    duration_days = Column(Integer, nullable=True)
    device_limit = Column(Integer, nullable=True)    # null = unlocked for reseller
    speed_limit_up = Column(BigInteger, nullable=True)    # Mbps; null = unlocked
    speed_limit_down = Column(BigInteger, nullable=True)  # Mbps; null = unlocked
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ResellerTrafficPackageOverride(Base):
    """Per-reseller price/bytes override for a global traffic package."""

    __tablename__ = "reseller_traffic_package_overrides"
    __table_args__ = (
        UniqueConstraint("admin_id", "package_id", name="uq_reseller_pkg_override"),
    )

    id = Column(Integer, primary_key=True)
    admin_id = Column(Integer, ForeignKey("admins.id"), index=True, nullable=False)
    package_id = Column(
        Integer, ForeignKey("reseller_traffic_packages.id"), index=True, nullable=False
    )
    price = Column(BigInteger, nullable=True)   # null = catalog price
    bytes = Column(BigInteger, nullable=True)   # null = catalog bytes

    admin = relationship("Admin", foreign_keys=[admin_id])
    package = relationship("ResellerTrafficPackage")


class ResellerPlanTariffOverride(Base):
    """Per-reseller wholesale price override for a global plan tariff."""

    __tablename__ = "reseller_plan_tariff_overrides"
    __table_args__ = (
        UniqueConstraint("admin_id", "tariff_id", name="uq_reseller_tariff_override"),
    )

    id = Column(Integer, primary_key=True)
    admin_id = Column(Integer, ForeignKey("admins.id"), index=True, nullable=False)
    tariff_id = Column(
        Integer, ForeignKey("reseller_plan_tariffs.id"), index=True, nullable=False
    )
    price = Column(BigInteger, nullable=True)  # null = catalog tariff price

    admin = relationship("Admin", foreign_keys=[admin_id])
    tariff = relationship("ResellerPlanTariff")


class ResellerTrafficPurchase(Base):
    """Ledger of reseller traffic package purchases and manual credits."""

    __tablename__ = "reseller_traffic_purchases"

    id = Column(Integer, primary_key=True)
    admin_id = Column(Integer, ForeignKey("admins.id"), index=True, nullable=False)
    package_id = Column(Integer, ForeignKey("reseller_traffic_packages.id"), nullable=True)
    bytes = Column(BigInteger, nullable=False)
    price_paid = Column(BigInteger, nullable=False, default=0)
    source = Column(String(16), nullable=False, default="purchase")  # purchase|manual
    created_by_admin_id = Column(Integer, ForeignKey("admins.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    admin = relationship("Admin", foreign_keys=[admin_id])
    package = relationship("ResellerTrafficPackage")


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


class UserOrder(Base):
    """End-user purchase of a plan (self-service renewal)."""

    __tablename__ = "user_orders"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    amount = Column(BigInteger, nullable=False)
    status = Column(String(16), nullable=False, default="pending", index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    paid_at = Column(DateTime, nullable=True)
    applied_at = Column(DateTime, nullable=True)

    user = relationship("User")
    plan = relationship("Plan")


class PlatformSetting(Base):
    """Key/value platform configuration editable from the admin UI."""

    __tablename__ = "platform_settings"

    key = Column(String(64), primary_key=True)
    value = Column(JSON, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ClientProbe(Base):
    """Network probe result reported by the SigmaGuard client (phase A).

    The app pings candidate nodes and POSTs the measurements; the panel stores
    them to refine node recommendations over time.
    """

    __tablename__ = "client_probes"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    node_id = Column(Integer, ForeignKey("nodes.id"), index=True, nullable=True)
    profile = Column(String(16), nullable=True)
    protocol = Column(String(32), nullable=True)
    ping_ms = Column(Float, nullable=True)
    packet_loss_pct = Column(Float, nullable=True)
    handshake_ms = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class ClientDevice(Base):
    """A push-notification target registered by the SigmaGuard app (phase B).

    One row per device token. Re-registering the same token only updates
    metadata for its *current* owner (upsert scoped to ``(user_id, token)``);
    a token already owned by a different user is rejected rather than
    silently reassigned (see AUDIT_FINDINGS.md H4) — the owning user must
    release it via ``DELETE /client/device-token`` first.
    """

    __tablename__ = "client_devices"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    token = Column(String(512), unique=True, nullable=False, index=True)
    platform = Column(String(16), nullable=True)  # 'android' | 'ios' | …
    app_version = Column(String(32), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ClientTelemetry(Base):
    """Per-session network-quality sample reported by the app (phase B)."""

    __tablename__ = "client_telemetry"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    session_id = Column(String(64), nullable=True, index=True)
    active_protocol = Column(String(32), nullable=True)
    active_node = Column(Integer, ForeignKey("nodes.id"), nullable=True)
    ping_ms = Column(Float, nullable=True)
    packet_loss_pct = Column(Float, nullable=True)
    bytes_sent = Column(BigInteger, nullable=True)
    bytes_recv = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class DedicatedIP(Base):
    """A static exit IP reserved for a single Trader account (phase B).

    Unassigned rows (``user_id IS NULL``) form the available pool. Once bound to
    a user the IP must never rotate; the client API surfaces it so the user can
    whitelist it on exchanges.
    """

    __tablename__ = "dedicated_ips"

    id = Column(Integer, primary_key=True)
    address = Column(String(64), unique=True, nullable=False, index=True)
    node_id = Column(Integer, ForeignKey("nodes.id"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, unique=True, index=True)
    assigned_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class UsageBillingCheckpoint(Base):
    """Tracks how far pay-as-you-go billing has advanced for a reseller."""

    __tablename__ = "usage_billing_checkpoints"

    admin_id = Column(Integer, ForeignKey("admins.id"), primary_key=True)
    last_billed_at = Column(DateTime, nullable=False)
    # Watermark on Admin.users_usage — covers every connection path the panel
    # records (VLESS/WG/Finalmask/sing-box), not just hourly NodeUserUsage rows.
    last_billed_users_usage = Column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )

    admin = relationship("Admin")


class PaymentIntent(Base):
    """A PSP checkout session for wallet top-up or portal plan purchase."""

    __tablename__ = "payment_intents"

    id = Column(Integer, primary_key=True)
    kind = Column(String(32), nullable=False)  # topup | portal_renew
    admin_id = Column(Integer, ForeignKey("admins.id"), index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=True)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=True)
    amount = Column(BigInteger, nullable=False)
    provider = Column(String(32), nullable=False)
    status = Column(String(16), nullable=False, default="pending", index=True)
    extra = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    admin = relationship("Admin")
    user = relationship("User")
    plan = relationship("Plan")


class AdminPushSubscription(Base):
    """Browser Web Push endpoint for an admin/reseller (card payment alerts)."""

    __tablename__ = "admin_push_subscriptions"

    id = Column(Integer, primary_key=True)
    admin_id = Column(Integer, ForeignKey("admins.id"), index=True, nullable=False)
    endpoint = Column(String(2048), unique=True, nullable=False)
    p256dh = Column(String(512), nullable=False)
    auth = Column(String(256), nullable=False)
    user_agent = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    admin = relationship("Admin")


class PortalPushSubscription(Base):
    """Browser Web Push endpoint for a portal end-user."""

    __tablename__ = "portal_push_subscriptions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    endpoint = Column(String(2048), unique=True, nullable=False)
    p256dh = Column(String(512), nullable=False)
    auth = Column(String(256), nullable=False)
    user_agent = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User")


class Invoice(Base):
    """A billable charge, optionally tied to a plan."""

    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True)
    admin_id = Column(Integer, ForeignKey("admins.id"), index=True, nullable=False)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=True)
    amount = Column(BigInteger, nullable=False)                 # minor units
    status = Column(String(16), nullable=False, default="pending", index=True)  # pending|paid|canceled
    provider = Column(String(32), nullable=True)
    description = Column(String(512), nullable=True)
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
    # Public panel login URL for this brand (shown to customers / copied by reseller).
    panel_url = Column(String(512), nullable=True)
    # Optional subscription URL customization (defaults: path ``sub``, port 443).
    sub_path = Column(String(64), nullable=True)
    sub_port = Column(Integer, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="branding")


class Tunnel(Base):
    """An encrypted hop between an in-country ``relay`` end and a foreign
    ``exit`` end (phase 6). Many protocols don't survive a direct connection
    from inside Iran, so clients hit the relay which forwards to the exit over a
    secure transport. The panel generates the relay outbound and exit inbound
    Xray fragments from this definition.

    Either end may be a registered :class:`Node` or the panel's own local Xray
    core (when ``relay_node_id`` / ``exit_node_id`` is ``NULL``). This lets a
    panel installed on an Iran box be the relay while only a foreign node is
    added as the exit (or vice versa).
    """

    __tablename__ = "tunnels"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    # A NULL endpoint means "the panel's own local Xray core" (the panel host
    # acts as that end of the tunnel). Otherwise it points at a node.
    relay_node_id = Column(Integer, ForeignKey("nodes.id"), nullable=True, index=True)
    # Optional transit hop (relay → transit → exit). NULL => classic 2-end tunnel.
    intermediate_node_id = Column(Integer, ForeignKey("nodes.id"), nullable=True, index=True)
    intermediate_port = Column(Integer, nullable=True)  # port the transit node listens on
    exit_node_id = Column(Integer, ForeignKey("nodes.id"), nullable=True, index=True)
    # Transport for the relay->exit hop: 'reality' | 'ws' | 'grpc' | 'tcp'.
    transport = Column(String(16), nullable=False, default="reality")
    listen_port = Column(Integer, nullable=False)        # port clients hit on the relay
    target_port = Column(Integer, nullable=False)        # port the exit listens on
    params = Column(JSON, nullable=True)                 # transport-specific (sni, path, keys...)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    relay_node = relationship("Node", foreign_keys=[relay_node_id])
    intermediate_node = relationship("Node", foreign_keys=[intermediate_node_id])
    exit_node = relationship("Node", foreign_keys=[exit_node_id])


class WgInterface(Base):
    """Auto-scaled WireGuard server interface on a node (plain WG only).

    When ``wg_autoscale`` is enabled the panel shards plain WireGuard peers
    across multiple kernel interfaces (wg0, wg2, …) instead of one /24. AWG
    listeners (typically wg1) stay on the legacy ``node_wireguard`` path.
    """

    __tablename__ = "wg_interfaces"
    __table_args__ = (UniqueConstraint("node_id", "name", name="uq_wg_interfaces_node_name"),)

    id = Column(Integer, primary_key=True)
    node_id = Column(Integer, ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(32), nullable=False)
    subnet = Column(String(64), nullable=False)
    listen_port = Column(Integer, nullable=False)
    private_key = Column(String(64), nullable=False)
    public_key = Column(String(64), nullable=False)
    peer_count = Column(Integer, nullable=False, server_default=text("0"), default=0)
    max_peers = Column(Integer, nullable=False, server_default=text("200"), default=200)
    slot_index = Column(Integer, nullable=False, server_default=text("0"), default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    node = relationship("Node", back_populates="wg_interfaces")
    peers = relationship("WgPeer", back_populates="interface", cascade="all, delete-orphan")


class WgPeer(Base):
    """A plain WireGuard peer managed by the auto-scale planner."""

    __tablename__ = "wg_peers"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_wg_peers_user_id"),
        UniqueConstraint("interface_id", "address", name="uq_wg_peers_iface_address"),
        UniqueConstraint("interface_id", "public_key", name="uq_wg_peers_iface_pubkey"),
    )

    id = Column(Integer, primary_key=True)
    interface_id = Column(Integer, ForeignKey("wg_interfaces.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    address = Column(String(64), nullable=False)
    private_key = Column(String(64), nullable=False)
    public_key = Column(String(64), nullable=False)
    preshared_key = Column(String(64), nullable=True)
    active = Column(Boolean, nullable=False, server_default=text("true"), default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    interface = relationship("WgInterface", back_populates="peers")
    user = relationship("User", back_populates="wg_peer")


class SubscriptionEndpoint(Base):
    """Route subscription requests by host + path prefix (3x-ui style per-panel URLs)."""

    __tablename__ = "subscription_endpoints"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_subscription_endpoints_slug"),
        UniqueConstraint("host", "path_prefix", name="uq_subscription_endpoints_host_path"),
    )

    id = Column(Integer, primary_key=True)
    slug = Column(String(64), nullable=False, index=True)
    host = Column(String(255), nullable=True)
    path_prefix = Column(String(64), nullable=False, index=True)
    public_base_url = Column(String(512), nullable=False, server_default=text("''"))
    listen_port = Column(Integer, nullable=True)
    inbound_tag = Column(String(64), nullable=True, index=True)
    export_mode = Column(String(32), nullable=False, server_default=text("'full'"))
    format_default = Column(String(32), nullable=True)
    legacy_panel_id = Column(String(64), nullable=True)
    enabled = Column(Boolean, nullable=False, server_default=text("true"), default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    token_aliases = relationship(
        "SubscriptionTokenAlias",
        back_populates="endpoint",
        cascade="all, delete-orphan",
    )


class SubscriptionTokenAlias(Base):
    """Legacy subscription tokens (3x-ui subId) mapped to users.

    Equivalent to panel.md ``legacy_sub_routes``: uniqueness is
    ``(endpoint_id, token)`` — the same subId may exist on different panels.
    """

    __tablename__ = "subscription_token_aliases"
    __table_args__ = (
        UniqueConstraint(
            "endpoint_id", "token", name="uq_subscription_token_aliases_endpoint_token"
        ),
    )

    id = Column(Integer, primary_key=True)
    token = Column(String(256), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    endpoint_id = Column(
        Integer, ForeignKey("subscription_endpoints.id", ondelete="CASCADE"), nullable=True, index=True
    )
    source = Column(String(64), nullable=False, server_default=text("'manual'"))
    created_at = Column(DateTime, default=datetime.utcnow)

    # ``user_id`` is NOT NULL with a DB-level ON DELETE CASCADE. Without
    # ``passive_deletes`` the ORM would try to NULL ``user_id`` when a user is
    # deleted (violating the NOT NULL constraint and aborting bulk deletes) —
    # defer to the DB cascade instead so deleting a user drops its aliases.
    user = relationship(
        "User",
        backref=backref(
            "subscription_token_aliases",
            passive_deletes=True,
            cascade="all, delete-orphan",
        ),
    )
    endpoint = relationship("SubscriptionEndpoint", back_populates="token_aliases")


class NodeSyncCursor(Base):
    """Per-node resumable WireGuard sync watermark (generation + cursor)."""

    __tablename__ = "node_sync_cursors"

    node_id = Column(Integer, ForeignKey("nodes.id", ondelete="CASCADE"), primary_key=True)
    generation = Column(Integer, nullable=False, server_default=text("0"), default=0)
    cursor_user_id = Column(Integer, nullable=False, server_default=text("0"), default=0)
    last_outbox_id = Column(Integer, nullable=False, server_default=text("0"), default=0)
    desired_hash = Column(String(64), nullable=True)
    applied_hash = Column(String(64), nullable=True)
    status = Column(String(32), nullable=False, server_default=text("'converged'"), default="converged")
    peers_done = Column(Integer, nullable=False, server_default=text("0"), default=0)
    peers_total = Column(Integer, nullable=False, server_default=text("0"), default=0)
    error = Column(String(512), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    node = relationship("Node", backref=backref("sync_cursor", uselist=False, cascade="all, delete-orphan"))


class PeerChangeOutbox(Base):
    """Delta queue for WireGuard peer upsert/remove (hot path, resumable)."""

    __tablename__ = "peer_change_outbox"

    id = Column(Integer, primary_key=True)
    op = Column(String(16), nullable=False)  # upsert | remove | disable
    user_id = Column(Integer, nullable=True, index=True)
    public_key = Column(String(128), nullable=True, index=True)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class ResellerApplication(Base):
    """Public become-a-reseller request awaiting sudo/parent approval."""

    __tablename__ = "reseller_applications"

    id = Column(Integer, primary_key=True)
    username = Column(String(34), nullable=False, index=True)
    # Held until approve/reject, then cleared.
    password_plain = Column(String(128), nullable=True)
    display_name = Column(String(128), nullable=True)
    contact = Column(String(256), nullable=True)
    message = Column(Text, nullable=True)
    status = Column(String(16), nullable=False, default="pending", server_default=text("'pending'"), index=True)
    # Parent reseller when applying via invite; NULL = platform-level application.
    parent_admin_id = Column(Integer, ForeignKey("admins.id"), nullable=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    invite_code = Column(String(32), nullable=True)
    created_admin_id = Column(Integer, ForeignKey("admins.id"), nullable=True)
    reviewed_by_admin_id = Column(Integer, ForeignKey("admins.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    reject_reason = Column(String(256), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
