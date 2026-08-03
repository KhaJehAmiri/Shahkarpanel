from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class PortalToken(BaseModel):
    access_token: str
    token_type: str = "bearer"


class PortalProfile(BaseModel):
    username: str
    status: str
    used_traffic: int
    overage_traffic: int = 0
    lifetime_used_traffic: int = 0
    data_limit: Optional[int] = None
    expire: Optional[int] = None
    device_limit: Optional[int] = None
    online_devices: int = 0
    subscription_url: str = ""
    public_subscription_url: str = ""
    client_subscription_url: str = ""
    portal_url: str = ""
    sub_token: Optional[str] = None
    online: bool = False
    online_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    note: Optional[str] = None
    support_url: Optional[str] = None
    is_portal_login: bool = False
    is_owned: bool = True
    must_change_credentials: bool = False


class PortalBootstrapBody(BaseModel):
    token: str = Field(min_length=8, max_length=64)


class PortalBootstrapResponse(BaseModel):
    username: str
    must_change_credentials: bool = True
    portal_url: str = "/portal/"


class PortalCompleteSetupBody(BaseModel):
    new_username: str = Field(min_length=3, max_length=32)
    new_password: str = Field(min_length=4, max_length=128)


class PortalAccountSummary(BaseModel):
    username: str
    status: str
    used_traffic: int = 0
    data_limit: Optional[int] = None
    expire: Optional[int] = None
    online: bool = False
    online_devices: int = 0
    is_portal_login: bool = False
    public_subscription_url: str = ""
    created_at: Optional[datetime] = None


class PortalAccountCreateBody(BaseModel):
    plan_id: int
    username: str = Field(min_length=3, max_length=32)
    provider: Optional[str] = None
    method: Optional[str] = None  # gateway | card


class PortalAccountRenewBody(BaseModel):
    plan_id: int
    provider: Optional[str] = None
    method: Optional[str] = None


class PortalSubTokenBody(BaseModel):
    """Empty body = auto-generate; ``token`` = custom id."""
    token: Optional[str] = Field(default=None, min_length=8, max_length=32)


class PortalSubTokenResponse(BaseModel):
    detail: str
    sub_token: str
    subscription_url: str
    public_subscription_url: str = ""


class PortalPasswordBody(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=4, max_length=128)


class PortalPlan(BaseModel):
    id: int
    name: str
    price: int
    data_limit: Optional[int] = None
    duration_days: Optional[int] = None
    device_limit: Optional[int] = None
    model_config = ConfigDict(from_attributes=True)


class PortalOrder(BaseModel):
    id: int
    plan_id: int
    plan_name: str
    amount: int
    status: str
    created_at: datetime
    paid_at: Optional[datetime] = None
    applied_at: Optional[datetime] = None


class PortalTransaction(BaseModel):
    """Message-style payment transaction for the portal feed."""

    id: int
    kind: str
    kind_label: str
    provider: str
    provider_label: str
    amount: int
    amount_label: str
    status: str
    status_label: str
    plan_id: Optional[int] = None
    plan_name: Optional[str] = None
    account: Optional[str] = None
    title: str
    body: str
    lines: List[str] = []
    date: str
    time: str
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    unread: bool = True
    can_pay: bool = False
    expires_at: Optional[datetime] = None


class PortalTxReadResponse(BaseModel):
    id: int
    unread: bool = False
    unread_count: int = 0
    read_count: int = 0


class PortalTxSummary(BaseModel):
    unread_count: int = 0
    read_count: int = 0


class PortalRenewResponse(BaseModel):
    detail: str
    order_id: int
    status: str
    new_expire: Optional[int] = None
    new_data_limit: Optional[int] = None


class PortalLoginForm(BaseModel):
    username: str
    password: str = Field(min_length=1)


class PortalSettingsModify(BaseModel):
    portal_enabled: Optional[bool] = None
    portal_password: Optional[str] = Field(default=None, min_length=4)


class PortalLinkItem(BaseModel):
    link: str
    protocol: str = ""
    remark: str = ""
    region_flag: str = ""
    region_name: str = ""
    address_hint: str = ""
    latency_ms: Optional[float] = None


class PortalSubUrl(BaseModel):
    label: str = ""
    slug: str = ""
    url: str
    import_url: Optional[str] = None
    export_mode: Optional[str] = None
    recommended: bool = False


class PortalNodeLink(BaseModel):
    id: int
    name: str
    address: str = ""
    region: Optional[str] = None
    region_flag: Optional[str] = None
    region_name: Optional[str] = None
    latency_ms: Optional[float] = None
    link: Optional[str] = None
    # Raw wg-quick INI for official WireGuard app QR / .conf download.
    # ``link`` may still be a wireguard:// URI for Xray-family apps.
    conf: Optional[str] = None
    protocol: str = ""


class PortalConfigs(BaseModel):
    config_available: bool = True
    block_reason: Optional[str] = None
    public_subscription_url: str = ""
    client_subscription_url: str = ""
    subscription_urls: List[PortalSubUrl] = []
    link_items: List[PortalLinkItem] = []
    links: List[str] = []
    wireguard_nodes: List[PortalNodeLink] = []
    singbox_nodes: List[PortalNodeLink] = []


class PortalUsageDay(BaseModel):
    date: str
    used_traffic: int = 0


class PortalDailyUsage(BaseModel):
    username: str
    days: List[PortalUsageDay]
    total: int = 0


class FamilyServiceInfo(BaseModel):
    id: str
    label: str
    category: str = "other"
    popular: bool = False
    aliases: List[str] = []
    domain_count: int = 0


class FamilyPresetInfo(BaseModel):
    id: str
    label: str
    hint: str = ""
    block_adult: bool = False
    block_ads: bool = False
    services: List[str] = []


class FamilyControlsResponse(BaseModel):
    username: str
    controls: dict
    services: List[FamilyServiceInfo] = []
    presets: List[FamilyPresetInfo] = []


class FamilyControlsPutBody(BaseModel):
    enabled: Optional[bool] = None
    block_adult: Optional[bool] = None
    block_ads: Optional[bool] = None
    services: Optional[List[str]] = None
    custom_domains: Optional[List[str]] = None
    schedule: Optional[dict] = None
    pin: Optional[str] = Field(default=None, max_length=32)
    new_pin: Optional[str] = Field(default=None, min_length=4, max_length=8)
    clear_pin: bool = False
    pause_minutes: Optional[int] = Field(default=None, ge=1, le=24 * 60)
