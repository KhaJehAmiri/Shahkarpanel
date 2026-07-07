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
    data_limit: Optional[int] = None
    expire: Optional[int] = None
    subscription_url: str = ""
    public_subscription_url: str = ""
    portal_url: str = ""


class PortalPlan(BaseModel):
    id: int
    name: str
    price: int
    data_limit: Optional[int] = None
    duration_days: Optional[int] = None
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
