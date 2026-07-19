"""Pydantic models for subscription endpoints and token aliases."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SubscriptionExportMode(str, Enum):
    full = "full"
    inbound_only = "inbound_only"


class SubscriptionEndpointBase(BaseModel):
    slug: str = Field(..., min_length=1, max_length=64)
    host: Optional[str] = Field(None, max_length=255)
    path_prefix: str = Field(..., min_length=1, max_length=64)
    public_base_url: str = Field("", max_length=512)
    listen_port: Optional[int] = Field(None, ge=1, le=65535)
    inbound_tag: Optional[str] = Field(None, max_length=64)
    export_mode: SubscriptionExportMode = SubscriptionExportMode.full
    format_default: Optional[str] = Field(None, max_length=32)
    legacy_panel_id: Optional[str] = Field(None, max_length=64)
    enabled: bool = True

    @field_validator("path_prefix", "slug")
    @classmethod
    def strip_slashes(cls, v: str) -> str:
        return (v or "").strip().strip("/")

    @field_validator("host")
    @classmethod
    def normalize_host(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        return v.strip().lower().split(":")[0] or None

    @field_validator("public_base_url")
    @classmethod
    def normalize_public_base_url(cls, v: str) -> str:
        return (v or "").strip().rstrip("/")


class SubscriptionEndpointCreate(SubscriptionEndpointBase):
    pass


class SubscriptionEndpointModify(BaseModel):
    slug: Optional[str] = Field(None, min_length=1, max_length=64)
    host: Optional[str] = Field(None, max_length=255)
    path_prefix: Optional[str] = Field(None, min_length=1, max_length=64)
    public_base_url: Optional[str] = Field(None, max_length=512)
    listen_port: Optional[int] = Field(None, ge=1, le=65535)
    inbound_tag: Optional[str] = Field(None, max_length=64)
    export_mode: Optional[SubscriptionExportMode] = None
    format_default: Optional[str] = Field(None, max_length=32)
    legacy_panel_id: Optional[str] = Field(None, max_length=64)
    enabled: Optional[bool] = None


class SubscriptionEndpointResponse(SubscriptionEndpointBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class InboundSubscriptionSettingsModify(BaseModel):
    """3x-ui-style per-inbound subscription settings.

    Field names mirror 3x-ui's inbound "Subscription" section so the concepts
    translate directly for admins migrating from 3x-ui:
    - ``host``            -> Listen Domain (blank = listen on all domains/IPs)
    - ``listen_port``     -> Listen Port
    - ``path_prefix``     -> URI Path (begins/ends with "/")
    - ``public_base_url`` -> Reverse Proxy URI
    """

    host: Optional[str] = Field(None, max_length=255)
    listen_port: Optional[int] = Field(None, ge=1, le=65535)
    path_prefix: str = Field(..., min_length=1, max_length=64)
    public_base_url: str = Field("", max_length=512)
    enabled: bool = True

    @field_validator("path_prefix")
    @classmethod
    def strip_slashes(cls, v: str) -> str:
        return (v or "").strip().strip("/")

    @field_validator("host")
    @classmethod
    def normalize_host(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        return v.strip().lower().split(":")[0] or None

    @field_validator("public_base_url")
    @classmethod
    def normalize_public_base_url(cls, v: str) -> str:
        return (v or "").strip().rstrip("/")


class InboundSubscriptionSettingsResponse(BaseModel):
    inbound_tag: str
    inherited: bool
    override: Optional[SubscriptionEndpointResponse] = None
    effective: Optional[SubscriptionEndpointResponse] = None


class SubscriptionSslStatusResponse(BaseModel):
    host: str
    cert_present: bool = False
    https_ready: bool = False
    https_vhost_staged: bool = False
    message: str = ""
    ok: bool = False
    sync_applied: Optional[bool] = None
    sync_message: str = ""


class SubscriptionTokenAliasCreate(BaseModel):
    token: str = Field(..., min_length=1, max_length=256)
    user_id: int
    endpoint_id: Optional[int] = None
    source: str = "manual"


class SubscriptionTokenAliasResponse(BaseModel):
    id: int
    token: str
    user_id: int
    endpoint_id: Optional[int] = None
    source: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
