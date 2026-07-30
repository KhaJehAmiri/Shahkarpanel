from typing import Dict, List, Optional

from pydantic import field_validator, ConfigDict, BaseModel, Field

from app import xray
from app.models.proxy import ProxyTypes
from app.models.user import UserDataLimitResetStrategy, UserStatusCreate

# Sentinel inbound tags persisted for native product protocols (no Xray inbound).
NATIVE_TEMPLATE_MARKERS: Dict[str, ProxyTypes] = {
    "__native:wireguard": ProxyTypes.WireGuard,
    "__native:amneziawg": ProxyTypes.WireGuard,
    "__native:hysteria2": ProxyTypes.Hysteria2,
    "__native:tuic": ProxyTypes.TUIC,
    "__native:anytls": ProxyTypes.AnyTLS,
}
NATIVE_TEMPLATE_PROTOCOLS = frozenset(p.value for p in NATIVE_TEMPLATE_MARKERS.values())


def native_template_marker(protocol: str) -> str:
    return f"__native:{protocol}"


def is_native_template_marker(tag: str) -> bool:
    return tag in NATIVE_TEMPLATE_MARKERS


class UserTemplate(BaseModel):
    name: Optional[str] = Field(None, nullable=True)
    data_limit: Optional[int] = Field(
        ge=0, default=None, description="data_limit can be 0 or greater"
    )
    expire_duration: Optional[int] = Field(
        ge=0, default=None, description="expire_duration can be 0 or greater in seconds"
    )
    username_prefix: Optional[str] = Field(max_length=20, min_length=1, default=None)
    username_suffix: Optional[str] = Field(max_length=20, min_length=1, default=None)
    data_limit_reset_strategy: Optional[UserDataLimitResetStrategy] = None
    default_status: Optional[UserStatusCreate] = None
    note: Optional[str] = Field(default=None, max_length=500)
    next_plan: Optional[dict] = None

    inbounds: Dict[ProxyTypes, List[str]] = {}


class UserTemplateCreate(UserTemplate):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "name": "my template 1",
            "username_prefix": None,
            "username_suffix": None,
            "inbounds": {"vmess": ["VMESS_INBOUND"], "vless": ["VLESS_INBOUND"]},
            "data_limit": 0,
            "expire_duration": 0,
        }
    })


class UserTemplateModify(UserTemplate):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "name": "my template 1",
            "username_prefix": None,
            "username_suffix": None,
            "inbounds": {"vmess": ["VMESS_INBOUND"], "vless": ["VLESS_INBOUND"]},
            "data_limit": 0,
            "expire_duration": 0,
        }
    })


class UserTemplateResponse(UserTemplate):
    id: int

    @field_validator("inbounds", mode="before")
    @classmethod
    def validate_inbounds(cls, v):
        final = {}
        inbound_tags = [i.tag for i in v]
        for protocol, inbounds in xray.config.inbounds_by_protocol.items():
            for inbound in inbounds:
                if inbound["tag"] in inbound_tags:
                    if protocol in final:
                        final[protocol].append(inbound["tag"])
                    else:
                        final[protocol] = [inbound["tag"]]
        for tag in inbound_tags:
            proto = NATIVE_TEMPLATE_MARKERS.get(tag)
            if proto is not None:
                final[proto.value] = []
        return final
    model_config = ConfigDict(from_attributes=True)
