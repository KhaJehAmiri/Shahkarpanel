import re
import secrets
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_serializer,
    field_validator,
    model_validator,
)

from app import xray
from app.models.admin import Admin
from app.models.proxy import ProxySettings, ProxyTypes
from app.subscription.share import generate_v2ray_links
from app.utils.jwt import create_subscription_token
from config import XRAY_SUBSCRIPTION_PATH, XRAY_SUBSCRIPTION_URL_PREFIX

# Keep in sync with portal live check + error copy shown to users.
# Allow A–Z: EMG / 3x-ui imports keep mixed-case usernames (e.g. emg1_PUnm…).
# Dots and other punctuation stay rejected (portal purchase safety).
USERNAME_REGEXP = re.compile(r"^[a-zA-Z0-9_]{3,32}$")


class ReminderType(str, Enum):
    expiration_date = "expiration_date"
    data_usage = "data_usage"


class UserStatus(str, Enum):
    active = "active"
    disabled = "disabled"
    limited = "limited"
    expired = "expired"
    on_hold = "on_hold"


class UserStatusModify(str, Enum):
    active = "active"
    disabled = "disabled"
    on_hold = "on_hold"
    limited = "limited"
    expired = "expired"


class UserStatusCreate(str, Enum):
    active = "active"
    on_hold = "on_hold"


class UserDataLimitResetStrategy(str, Enum):
    no_reset = "no_reset"
    day = "day"
    week = "week"
    month = "month"
    year = "year"


class NextPlanModel(BaseModel):
    data_limit: Optional[int] = None
    expire: Optional[int] = None
    add_remaining_traffic: bool = False
    fire_on_either: bool = True
    model_config = ConfigDict(from_attributes=True)


class User(BaseModel):
    proxies: Dict[ProxyTypes, ProxySettings] = {}
    expire: Optional[int] = Field(None, nullable=True)
    data_limit: Optional[int] = Field(
        ge=0, default=None, description="data_limit can be 0 or greater"
    )
    data_limit_reset_strategy: UserDataLimitResetStrategy = (
        UserDataLimitResetStrategy.no_reset
    )
    inbounds: Dict[ProxyTypes, List[str]] = Field(default_factory=dict, validate_default=True)
    note: Optional[str] = Field(None, nullable=True)
    sub_updated_at: Optional[datetime] = Field(None, nullable=True)
    sub_last_user_agent: Optional[str] = Field(None, nullable=True)
    online_at: Optional[datetime] = Field(None, nullable=True)
    on_hold_expire_duration: Optional[int] = Field(None, nullable=True)
    on_hold_timeout: Optional[Union[datetime, None]] = Field(None, nullable=True)

    auto_delete_in_days: Optional[int] = Field(None, nullable=True)

    next_plan: Optional[NextPlanModel] = Field(None, nullable=True)

    device_limit: Optional[int] = Field(None, nullable=True, ge=0)

    @field_serializer("online_at")
    def serialize_online_at_utc(self, value: Optional[datetime]) -> Optional[str]:
        """Emit UTC with a Z suffix so browsers don't treat naive ISO as local time.

        Backend stores naive UTC. Without Z, Iran (UTC+3:30) showed last-online
        ~3.5 hours in the past even when the account was live.
        """
        if value is None:
            return None
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value.isoformat(timespec="seconds") + "Z"
    speed_limit_up: Optional[int] = Field(None, nullable=True, ge=0, description="Upload cap in Mbps")
    speed_limit_down: Optional[int] = Field(None, nullable=True, ge=0, description="Download cap in Mbps")
    routing_preset: Optional[str] = Field(None, nullable=True)
    dns_policy: Optional[dict] = Field(None, nullable=True)
    family_controls: Optional[dict] = Field(None, nullable=True)
    session_limit_minutes: Optional[int] = Field(None, nullable=True, ge=0)

    # SigmaGuard client profile. None on a patch = leave unchanged.
    client_profile: Optional[str] = Field(default=None, nullable=True)

    @field_validator("client_profile")
    @classmethod
    def validate_client_profile(cls, v):
        if v is not None and v not in ("gamer", "trader", "normal"):
            raise ValueError("client_profile must be gamer, trader, or normal")
        return v

    @field_validator('data_limit', mode='before')
    def cast_to_int(cls, v):
        if v is None:  # Allow None values
            return v
        if isinstance(v, float):  # Allow float to int conversion
            return int(v)
        if isinstance(v, int):  # Allow integers directly
            return v
        raise ValueError("data_limit must be an integer or a float, not a string")  # Reject strings

    @field_validator("proxies", mode="before")
    def validate_proxies(cls, v, values, **kwargs):
        if not v:
            raise ValueError("Each user needs at least one proxy")
        return {
            proxy_type: ProxySettings.from_dict(
                proxy_type, v.get(proxy_type, {}))
            for proxy_type in v
        }

    @field_validator("username", check_fields=False)
    @classmethod
    def validate_username(cls, v):
        if not USERNAME_REGEXP.match(v):
            raise ValueError(
                "Username only can be 3 to 32 characters and contain a-z, A-Z, 0-9, and underscores."
            )
        return v

    @field_validator("note", check_fields=False)
    @classmethod
    def validate_note(cls, v):
        if v and len(v) > 500:
            raise ValueError("User's note can be a maximum of 500 character")
        return v

    @field_validator("on_hold_expire_duration", "on_hold_timeout", mode="before")
    def validate_timeout(cls, v, values):
        # Check if expire is 0 or None and timeout is not 0 or None
        if (v in (0, None)):
            return None
        return v


class UserCreate(User):
    username: str
    status: UserStatusCreate = None
    portal_enabled: bool = False
    portal_password: Optional[str] = Field(default=None, min_length=4)
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "username": "user1234",
            "proxies": {
                "vmess": {"id": "35e4e39c-7d5c-4f4b-8b71-558e4f37ff53"},
                "vless": {},
            },
            "inbounds": {
                "vmess": ["VMess TCP", "VMess Websocket"],
                "vless": ["VLESS TCP REALITY", "VLESS GRPC REALITY"],
            },
            "next_plan": {
                "data_limit": 0,
                "expire": 0,
                "add_remaining_traffic": False,
                "fire_on_either": True
            },
            "expire": 0,
            "data_limit": 0,
            "data_limit_reset_strategy": "no_reset",
            "status": "active",
            "note": "",
            "on_hold_timeout": "2023-11-03T20:30:00",
            "on_hold_expire_duration": 0,
        }
    })

    @property
    def excluded_inbounds(self):
        excluded = {}
        for proxy_type in self.proxies:
            excluded[proxy_type] = []
            for inbound in xray.config.product_inbounds_for_type(proxy_type):
                if not inbound["tag"] in self.inbounds.get(proxy_type, []):
                    excluded[proxy_type].append(inbound["tag"])

        return excluded

    @field_validator("inbounds", mode="before")
    def validate_inbounds(cls, inbounds, values, **kwargs):
        proxies = values.data.get("proxies", [])

        from app.xray.inbound_match import align_shadowsocks_from_inbounds, inbound_matches_proxy

        if inbounds and proxies:
            align_shadowsocks_from_inbounds(proxies, inbounds)

        # delete inbounds that are for protocols not activated
        for proxy_type in inbounds.copy():
            if proxy_type not in proxies:
                del inbounds[proxy_type]

        # check by proxies to ensure that every protocol has inbounds set
        for proxy_type in list(proxies):
            ptype = proxy_type if isinstance(proxy_type, ProxyTypes) else ProxyTypes(str(proxy_type))
            if ptype in (ProxyTypes.WireGuard, ProxyTypes.Hysteria2, ProxyTypes.TUIC, ProxyTypes.AnyTLS):
                inbounds[proxy_type] = inbounds.get(proxy_type) or []
                continue

            proxy_settings = proxies.get(proxy_type)
            tags = inbounds.get(proxy_type)
            # Missing or explicitly empty → auto-select compatible product inbounds.
            # Empty lists used to raise ("inbounds cannot be empty") and blocked
            # portal purchase approve when the owner blueprint copied Shadowsocks
            # with no usable tags on this panel.
            if not tags:
                tags = [
                    i["tag"]
                    for i in xray.config.inbounds_by_protocol.get(ptype.value, [])
                    if inbound_matches_proxy(
                        proxy_type, i["tag"], proxy_settings, inbound_meta=i
                    )
                ]
                inbounds[proxy_type] = tags

            if not tags:
                # Panel cannot serve this protocol — drop it instead of failing
                # the whole create (common when cloning a multi-protocol owner
                # onto a VLESS-only panel).
                proxies.pop(proxy_type, None)
                inbounds.pop(proxy_type, None)
                continue

            for tag in tags:
                if tag not in xray.config.inbounds_by_tag:
                    raise ValueError(f"Inbound {tag} doesn't exist")
                if not inbound_matches_proxy(proxy_type, tag, proxy_settings):
                    raise ValueError(
                        f"Inbound {tag} is not compatible with {proxy_type} settings"
                    )

        if not proxies:
            raise ValueError("No compatible proxy protocols configured on this panel")

        return inbounds

    @field_validator("status", mode="before")
    def validate_status(cls, status, values):
        on_hold_expire = values.data.get("on_hold_expire_duration")
        expire = values.data.get("expire")
        if status == UserStatusCreate.on_hold:
            if (on_hold_expire == 0 or on_hold_expire is None):
                raise ValueError("User cannot be on hold without a valid on_hold_expire_duration.")
            if expire:
                raise ValueError("User cannot be on hold with specified expire.")
        return status


class UserModify(User):
    # Patches only — merged with existing DB settings in crud.update_user so
    # omitted credential fields (id/password/keys) are never regenerated.
    proxies: Dict[ProxyTypes, Dict[str, Any]] = Field(default_factory=dict)
    status: UserStatusModify = None
    data_limit_reset_strategy: UserDataLimitResetStrategy = None
    portal_enabled: Optional[bool] = None
    portal_password: Optional[str] = Field(default=None, min_length=4)
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "proxies": {
                "vmess": {"id": "35e4e39c-7d5c-4f4b-8b71-558e4f37ff53"},
                "vless": {},
            },
            "inbounds": {
                "vmess": ["VMess TCP", "VMess Websocket"],
                "vless": ["VLESS TCP REALITY", "VLESS GRPC REALITY"],
            },
            "next_plan": {
                "data_limit": 0,
                "expire": 0,
                "add_remaining_traffic": False,
                "fire_on_either": True
            },
            "expire": 0,
            "data_limit": 0,
            "data_limit_reset_strategy": "no_reset",
            "status": "active",
            "note": "",
            "on_hold_timeout": "2023-11-03T20:30:00",
            "on_hold_expire_duration": 0,
        }
    })

    @property
    def excluded_inbounds(self):
        excluded = {}
        for proxy_type in self.inbounds:
            excluded[proxy_type] = []
            for inbound in xray.config.inbounds_by_protocol.get(proxy_type, []):
                if not inbound["tag"] in self.inbounds.get(proxy_type, []):
                    excluded[proxy_type].append(inbound["tag"])

        return excluded

    @field_validator("inbounds", mode="before")
    def validate_inbounds(cls, inbounds, values, **kwargs):
        # check with inbounds, "proxies" is optional on modifying
        # so inbounds particularly can be modified
        if inbounds:
            from app.xray.inbound_match import align_shadowsocks_from_inbounds, inbound_matches_proxy

            proxies = values.data.get("proxies") or {}
            if proxies:
                align_shadowsocks_from_inbounds(proxies, inbounds)
            for proxy_type, tags in inbounds.items():
                for tag in tags:
                    if tag not in xray.config.inbounds_by_tag:
                        raise ValueError(f"Inbound {tag} doesn't exist")
                    if proxy_type in proxies and not inbound_matches_proxy(
                        proxy_type, tag, proxies[proxy_type]
                    ):
                        raise ValueError(
                            f"Inbound {tag} is not compatible with {proxy_type} settings"
                        )

        return inbounds

    @field_validator("proxies", mode="before")
    def validate_proxies(cls, v):
        if not v:
            return {}
        out: Dict[ProxyTypes, Dict[str, Any]] = {}
        for proxy_type, settings in v.items():
            ptype = proxy_type if isinstance(proxy_type, ProxyTypes) else ProxyTypes(str(proxy_type))
            out[ptype] = dict(settings) if isinstance(settings, dict) else dict(settings)
        return out

    @field_validator("status", mode="before")
    def validate_status(cls, status, values):
        on_hold_expire = values.data.get("on_hold_expire_duration")
        expire = values.data.get("expire")
        if status == UserStatusCreate.on_hold:
            if (on_hold_expire == 0 or on_hold_expire is None):
                raise ValueError("User cannot be on hold without a valid on_hold_expire_duration.")
            if expire:
                raise ValueError("User cannot be on hold with specified expire.")
        return status


class SubscriptionLinkItem(BaseModel):
    link: str
    protocol: str = ""
    remark: str = ""
    region_flag: str = ""
    region_name: str = ""
    address_hint: str = ""
    # Panel→node health probe RTT (ms). Same source as WireGuard cards.
    latency_ms: float | None = None


class WireGuardNodeItem(BaseModel):
    id: int
    name: str
    address: str
    region: str | None = None
    region_flag: str | None = None
    region_name: str | None = None
    latency_ms: float | None = None
    # Backward-compatible primary URI (plain preferred, else Xray/Finalmask).
    wireguard_uri: str | None = None
    wireguard_variant: str | None = None
    # Dual exports: stock WireGuard app (.conf / plain URI) vs Xray apps (fm=).
    wireguard_plain_uri: str | None = None
    wireguard_xray_uri: str | None = None
    plain_available: bool = False
    xray_available: bool = False
    wireguard_direct_uri: str | None = None
    awg_available: bool = False


class SingBoxNodeItem(BaseModel):
    id: int
    name: str
    address: str
    region: str | None = None
    region_flag: str | None = None
    region_name: str | None = None
    latency_ms: float | None = None
    hysteria2_link: str | None = None
    tuic_link: str | None = None
    anytls_link: str | None = None
    hysteria2_available: bool = False
    tuic_available: bool = False
    anytls_available: bool = False


class UserResponse(User):
    id: Optional[int] = None
    username: str
    status: UserStatus
    used_traffic: int
    used_traffic_up: int = 0
    used_traffic_down: int = 0
    overage_traffic: int = 0
    lifetime_used_traffic: int = 0
    created_at: datetime
    sub_token: Optional[str] = None
    session_limit_minutes: Optional[int] = None
    routing_preset: Optional[str] = None
    dns_policy: Optional[dict] = None
    family_controls: Optional[dict] = None
    sub_revoked_at: Optional[datetime] = None
    portal_enabled: bool = False
    links: List[str] = []
    link_items: List[SubscriptionLinkItem] = []
    subscription_url: str = ""
    public_subscription_url: str = ""
    client_subscription_url: str = ""
    subscription_profile_title: str = ""
    subscription_urls: List[dict] = []
    proxies: dict
    excluded_inbounds: Dict[ProxyTypes, List[str]] = {}

    admin: Optional[Admin] = None
    model_config = ConfigDict(from_attributes=True)

    @field_serializer("family_controls")
    def serialize_family_controls(self, value: Optional[dict]) -> Optional[dict]:
        if not value:
            return value
        from app.family_guard.policy import public_controls

        return public_controls(value)

    @model_validator(mode="after")
    def validate_links(self, info: ValidationInfo):
        if info.context and info.context.get("skip_default_links"):
            return self
        if not self.links:
            self.links = generate_v2ray_links(
                self.proxies, self.inbounds, extra_data=self.model_dump(), reverse=False,
            )
        if not self.link_items and self.links:
            from app.subscription.share import link_items_from_urls

            self.link_items = [SubscriptionLinkItem(**item) for item in link_items_from_urls(self.links)]
        return self

    @model_validator(mode="after")
    def validate_subscription_url(self, info: ValidationInfo):
        skip_heavy = bool(info.context and info.context.get("skip_default_links"))
        if not self.subscription_url:
            salt = secrets.token_hex(8)
            url_prefix = (XRAY_SUBSCRIPTION_URL_PREFIX).replace('*', salt)
            if getattr(self, "sub_token", None):
                token = self.sub_token
            else:
                # Legacy signed token — stable per username until revoke.
                issued_at = None
                if self.sub_revoked_at:
                    revoked_utc = self.sub_revoked_at.replace(tzinfo=timezone.utc)
                    issued_at = int(revoked_utc.timestamp()) + 1
                token = create_subscription_token(self.username, issued_at=issued_at)
            self.subscription_url = f"{url_prefix}/{XRAY_SUBSCRIPTION_PATH}/{token}"
        from app.subscription.public_url import public_subscription_url, list_user_subscription_urls
        from app.subscription.userinfo import format_subscription_profile_title, subscription_client_import_url

        self.public_subscription_url = public_subscription_url(self)
        # Prefer the endpoint-aware public URL (migrated panels use alias +
        # :2096 / custom domain). The generic XRAY_SUBSCRIPTION_URL_PREFIX link
        # points at the wrong host/token for those users.
        if self.public_subscription_url:
            self.subscription_url = self.public_subscription_url
        # Keep a title already set by the subscription router (tenant branding).
        if not (self.subscription_profile_title or "").strip():
            self.subscription_profile_title = format_subscription_profile_title(self)
        if not (self.client_subscription_url or "").strip():
            self.client_subscription_url = subscription_client_import_url(
                self.public_subscription_url, self
            )
        else:
            # Ensure fragment stays aligned when only the title was pre-set.
            pass
        if skip_heavy:
            # Bulk create only needs the share URL — skip enumerating every
            # format (json/clash/…) which fans out DB + link generation.
            self.subscription_urls = []
            return self
        try:
            self.subscription_urls = list_user_subscription_urls(self)
        except Exception:
            self.subscription_urls = []
        return self

    @field_validator("proxies", mode="before")
    def validate_proxies(cls, v, values, **kwargs):
        if isinstance(v, list):
            # Highest id wins so a leftover duplicate cannot hide the row
            # subscription / .conf already exported.
            ordered = sorted(
                v,
                key=lambda p: int(getattr(p, "id", 0) or 0),
            )
            v = {p.type: p.settings for p in ordered}
        return super().validate_proxies(v, values, **kwargs)

    @field_validator("used_traffic", "used_traffic_up", "used_traffic_down", "overage_traffic", "lifetime_used_traffic", mode='before')
    def cast_to_int(cls, v):
        if v is None:  # Allow None values
            return v
        if isinstance(v, float):  # Allow float to int conversion
            return int(v)
        if isinstance(v, int):  # Allow integers directly
            return v
        raise ValueError("must be an integer or a float, not a string")  # Reject strings


class SubscriptionBranding(BaseModel):
    panel_title: Optional[str] = None
    logo_url: Optional[str] = None
    favicon_url: Optional[str] = None
    primary_color: Optional[str] = None
    support_url: Optional[str] = None
    sub_profile_title: Optional[str] = None


class SubscriptionUserResponse(UserResponse):
    admin: Admin | None = Field(default=None, exclude=True)
    excluded_inbounds: Dict[ProxyTypes, List[str]] | None = Field(None, exclude=True)
    note: str | None = Field(None, exclude=True)
    inbounds: Dict[ProxyTypes, List[str]] | None = Field(None, exclude=True)
    auto_delete_in_days: int | None = Field(None, exclude=True)
    config_available: bool = True
    block_reason: str | None = None
    block_message: str | None = None
    minutes_left: int | None = None
    lockout_seconds_left: int | None = None
    blocked_devices: List[dict] = []
    public_subscription_url: str | None = None
    subscription_urls: List[dict] = []
    hysteria2_link: str | None = None
    tuic_link: str | None = None
    anytls_link: str | None = None
    wireguard_uri: str | None = None
    wireguard_variant: str | None = None
    wireguard_plain_uri: str | None = None
    wireguard_xray_uri: str | None = None
    wireguard_awg_available: bool = False
    wireguard_nodes: List[WireGuardNodeItem] = []
    singbox_nodes: List[SingBoxNodeItem] = []
    link_items: List[SubscriptionLinkItem] = []
    branding: Optional[SubscriptionBranding] = None
    # Concurrent subscription clients currently online (see count_online_devices).
    online_devices: int = 0
    online: bool = False
    model_config = ConfigDict(from_attributes=True)


class UserListItem(BaseModel):
    """Lightweight row for GET /users — skips subscription link generation."""

    id: Optional[int] = None
    username: str
    status: UserStatus
    used_traffic: int
    used_traffic_up: int = 0
    used_traffic_down: int = 0
    overage_traffic: int = 0
    created_at: datetime
    expire: Optional[int] = None
    data_limit: Optional[int] = None
    data_limit_reset_strategy: UserDataLimitResetStrategy = UserDataLimitResetStrategy.no_reset
    note: Optional[str] = None
    online_at: Optional[datetime] = None
    online: bool = False
    portal_enabled: bool = False
    proxies: Dict[str, Any] = {}
    inbounds: Dict[str, List[str]] = {}
    admin: Optional[Admin] = None

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("online_at")
    def serialize_list_online_at_utc(self, value: Optional[datetime]) -> Optional[str]:
        if value is None:
            return None
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value.isoformat(timespec="seconds") + "Z"

    @field_validator("proxies", mode="before")
    @classmethod
    def proxies_dict(cls, v):
        if isinstance(v, list):
            out: Dict[str, Any] = {}
            ordered = sorted(v, key=lambda p: int(getattr(p, "id", 0) or 0))
            for proxy in ordered:
                key = proxy.type.value if hasattr(proxy.type, "value") else str(proxy.type)
                settings = proxy.settings
                out[key] = settings if isinstance(settings, dict) else dict(settings or {})
            return out
        return v or {}

    @model_validator(mode="after")
    def _compute_online(self):
        """Derive live "online now" from ``online_at`` using the same window as
        the dashboard counter, so the source of truth stays server-side."""
        if self.online_at is not None:
            from datetime import datetime, timedelta

            from config import ONLINE_WINDOW_MINUTES

            seen = self.online_at
            if isinstance(seen, str):
                raw = seen[:-1] if seen.endswith("Z") else seen
                try:
                    seen = datetime.fromisoformat(raw)
                except ValueError:
                    return self
            if seen.tzinfo is not None:
                seen = seen.replace(tzinfo=None)
            if datetime.utcnow() - seen <= timedelta(minutes=ONLINE_WINDOW_MINUTES):
                object.__setattr__(self, "online", True)
        return self

    @field_validator(
        "used_traffic",
        "used_traffic_up",
        "used_traffic_down",
        "overage_traffic",
        mode="before",
    )
    @classmethod
    def cast_to_int(cls, v):
        if v is None:
            return v
        if isinstance(v, float):
            return int(v)
        if isinstance(v, int):
            return v
        raise ValueError("must be an integer or a float, not a string")


class UsersResponse(BaseModel):
    users: List[UserListItem]
    total: int


class UserUsageResponse(BaseModel):
    node_id: Union[int, None] = None
    node_name: str
    used_traffic: int

    @field_validator("used_traffic",  mode='before')
    def cast_to_int(cls, v):
        if v is None:  # Allow None values
            return v
        if isinstance(v, float):  # Allow float to int conversion
            return int(v)
        if isinstance(v, int):  # Allow integers directly
            return v
        raise ValueError("must be an integer or a float, not a string")  # Reject strings


class UserDailyUsageDay(BaseModel):
    date: str  # YYYY-MM-DD (UTC)
    used_traffic: int = 0


class UserDailyUsagesResponse(BaseModel):
    username: str
    days: List[UserDailyUsageDay]
    total: int = 0


class UserUsagesResponse(BaseModel):
    username: str
    usages: List[UserUsageResponse]


class UsersUsagesResponse(BaseModel):
    usages: List[UserUsageResponse]
