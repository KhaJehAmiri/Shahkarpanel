import json
import re
from enum import Enum
from typing import Optional, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

import base64
import secrets

from app.utils.system import random_password
from xray_api.types.account import (
    SS2022_KEY_BYTES,
    SS2022_METHODS,
    ShadowsocksAccount,
    ShadowsocksMethods,
    TrojanAccount,
    VLESSAccount,
    VMessAccount,
    XTLSFlows,
)


def random_ss2022_key(method: ShadowsocksMethods) -> str:
    """Return a base64 PSK of the exact byte-length the SS-2022 cipher needs."""
    n = SS2022_KEY_BYTES.get(method, 32)
    return base64.b64encode(secrets.token_bytes(n)).decode()


def _is_valid_ss2022_key(value: str, method: ShadowsocksMethods) -> bool:
    try:
        raw = base64.b64decode(value, validate=True)
    except Exception:
        return False
    return len(raw) == SS2022_KEY_BYTES.get(method, 32)

FRAGMENT_PATTERN = re.compile(r'^((\d{1,4}-\d{1,4})|(\d{1,4})),((\d{1,3}-\d{1,3})|(\d{1,3})),(tlshello|\d|\d\-\d)$')

NOISE_PATTERN = re.compile(
    r'^(rand:(\d{1,4}-\d{1,4}|\d{1,4})|str:.+|hex:.+|base64:.+)(,(\d{1,4}-\d{1,4}|\d{1,4}))?(&(rand:(\d{1,4}-\d{1,4}|\d{1,4})|str:.+|hex:.+|base64:.+)(,(\d{1,4}-\d{1,4}|\d{1,4}))?)*$')


class ProxyTypes(str, Enum):
    # proxy_type = protocol

    VMess = "vmess"
    VLESS = "vless"
    Trojan = "trojan"
    Shadowsocks = "shadowsocks"
    # WireGuard is a *product* protocol served by a native WireGuard interface
    # on the node (not an Xray account). It shares the user's central
    # used_traffic; see docs/accounting-contract.md.
    WireGuard = "wireguard"
    # Hysteria2 and TUIC are QUIC *product* protocols served by the node's
    # sing-box engine (not Xray accounts). Like WireGuard they fold into the
    # single used_traffic; see docs/accounting-contract.md.
    Hysteria2 = "hysteria2"
    TUIC = "tuic"

    @property
    def account_model(self):
        if self == self.VMess:
            return VMessAccount
        if self == self.VLESS:
            return VLESSAccount
        if self == self.Trojan:
            return TrojanAccount
        if self == self.Shadowsocks:
            return ShadowsocksAccount
        # WireGuard / Hysteria2 / TUIC have no Xray account; they are
        # provisioned on the node's native engine (WireGuard / sing-box).
        if self in (self.WireGuard, self.Hysteria2, self.TUIC):
            return None

    @property
    def settings_model(self):
        if self == self.VMess:
            return VMessSettings
        if self == self.VLESS:
            return VLESSSettings
        if self == self.Trojan:
            return TrojanSettings
        if self == self.Shadowsocks:
            return ShadowsocksSettings
        if self == self.WireGuard:
            return WireGuardSettings
        if self == self.Hysteria2:
            return Hysteria2Settings
        if self == self.TUIC:
            return TUICSettings

    @property
    def is_xray_account(self) -> bool:
        """True when this protocol is provisioned through the Xray handler
        (and therefore reports usage via the Xray Stats API)."""
        return self not in (self.WireGuard, self.Hysteria2, self.TUIC)

    @property
    def is_singbox_product(self) -> bool:
        """True for protocols served by the node's sing-box engine."""
        return self in (self.Hysteria2, self.TUIC)


class ProxySettings(BaseModel, use_enum_values=True):
    @classmethod
    def from_dict(cls, proxy_type: ProxyTypes, _dict: dict):
        return ProxyTypes(proxy_type).settings_model.model_validate(_dict)

    def dict(self, *, no_obj=False, **kwargs):
        if no_obj:
            return json.loads(self.json())
        return super().dict(**kwargs)


def apply_proxy_patch(
    proxy_type: ProxyTypes,
    existing: Optional[dict],
    patch: dict,
) -> dict:
    """Merge a partial API patch into stored proxy settings.

    User edits often send only non-secret fields (e.g. VLESS ``flow``) while
    omitting ``id``/``password``.  Merging with the DB row first keeps existing
    credentials stable; only keys present in ``patch`` are updated.

    ``existing``/``patch`` may be plain dicts (API edits, ``UserModify``) or
    ``ProxySettings`` objects (e.g. ``revoke_user_sub`` passes a mutated
    settings model). Both are coerced to mappings before merging so callers
    never hit "X object is not a mapping".
    """
    def _as_mapping(value) -> dict:
        if value is None:
            return {}
        if isinstance(value, ProxySettings):
            return value.dict(no_obj=True)
        if isinstance(value, dict):
            return value
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        return dict(value)

    merged = {**_as_mapping(existing), **_as_mapping(patch)}
    return ProxySettings.from_dict(proxy_type, merged).dict(no_obj=True)


class VMessSettings(ProxySettings):
    id: UUID = Field(default_factory=uuid4)

    def revoke(self):
        self.id = uuid4()


class VLESSSettings(ProxySettings):
    id: UUID = Field(default_factory=uuid4)
    flow: XTLSFlows = XTLSFlows.NONE

    def revoke(self):
        self.id = uuid4()


class TrojanSettings(ProxySettings):
    password: str = Field(default_factory=random_password)
    flow: XTLSFlows = XTLSFlows.NONE

    def revoke(self):
        self.password = random_password()


class ShadowsocksSettings(ProxySettings):
    password: str = Field(default_factory=random_password)
    method: ShadowsocksMethods = ShadowsocksMethods.CHACHA20_POLY1305

    @model_validator(mode="after")
    def _ensure_key_matches_method(self):
        # SS-2022 ciphers need a base64 PSK of an exact length. If the method is
        # 2022 but the stored password isn't a valid key (e.g. a legacy
        # plain-text password or a method switch), mint a correct one.
        method = self.method if isinstance(self.method, ShadowsocksMethods) else ShadowsocksMethods(self.method)
        if method in SS2022_METHODS and not _is_valid_ss2022_key(self.password, method):
            self.password = random_ss2022_key(method)
        return self

    def revoke(self):
        method = self.method if isinstance(self.method, ShadowsocksMethods) else ShadowsocksMethods(self.method)
        if method in SS2022_METHODS:
            self.password = random_ss2022_key(method)
        else:
            self.password = random_password()


class WireGuardSettings(ProxySettings):
    """Per-user WireGuard credentials.

    ``private_key`` is the user's secret (used only to render their .conf);
    ``public_key`` is what the node peers on. ``address`` is the peer IP
    (e.g. ``10.10.0.5/32``) allocated from the WireGuard node's subnet when the
    user is assigned to a node — it stays ``None`` until then. Keys are
    auto-generated when absent so an empty ``{}`` from the API yields a valid
    peer.
    """
    private_key: str = ""
    public_key: str = ""
    address: Optional[str] = None
    preshared_key: Optional[str] = None

    @model_validator(mode="after")
    def _ensure_keys(self):
        from app.wireguard.keys import generate_keypair, public_key_from_private

        if not self.private_key:
            priv, pub = generate_keypair()
            self.private_key = priv
            self.public_key = pub
        elif not self.public_key:
            self.public_key = public_key_from_private(self.private_key)
        return self

    def revoke(self):
        from app.wireguard.keys import generate_keypair

        priv, pub = generate_keypair()
        self.private_key = priv
        self.public_key = pub


class Hysteria2Settings(ProxySettings):
    """Per-user Hysteria2 credentials (served by the node's sing-box engine).

    ``password`` is the per-user auth string sing-box checks against its
    inbound user list. Auto-generated when absent so an empty ``{}`` from the
    API yields a valid user.
    """
    password: str = Field(default_factory=random_password)

    def revoke(self):
        self.password = random_password()


class TUICSettings(ProxySettings):
    """Per-user TUIC credentials (served by the node's sing-box engine).

    TUIC authenticates with a ``uuid`` + ``password`` pair.
    """
    uuid: UUID = Field(default_factory=uuid4)
    password: str = Field(default_factory=random_password)

    def revoke(self):
        self.uuid = uuid4()
        self.password = random_password()


class ProxyHostSecurity(str, Enum):
    inbound_default = "inbound_default"
    none = "none"
    tls = "tls"


ProxyHostALPN = Enum(
    "ProxyHostALPN",
    {
        "none": "",
        "h3": "h3",
        "h2": "h2",
        "http/1.1": "http/1.1",
        "h3,h2,http/1.1": "h3,h2,http/1.1",
        "h3,h2": "h3,h2",
        "h2,http/1.1": "h2,http/1.1",
    },
)


ProxyHostFingerprint = Enum(
    "ProxyHostFingerprint",
    {
        "none": "",
        "chrome": "chrome",
        "firefox": "firefox",
        "safari": "safari",
        "ios": "ios",
        "android": "android",
        "edge": "edge",
        "360": "360",
        "qq": "qq",
        "random": "random",
        "randomized": "randomized",
    },
)


class FormatVariables(dict):
    def __missing__(self, key):
        return key.join("{}")


class ProxyHost(BaseModel):
    remark: str
    address: str
    port: Optional[int] = Field(None, nullable=True)
    sni: Optional[str] = Field(None, nullable=True)
    host: Optional[str] = Field(None, nullable=True)
    path: Optional[str] = Field(None, nullable=True)
    security: ProxyHostSecurity = ProxyHostSecurity.inbound_default
    alpn: ProxyHostALPN = ProxyHostALPN.none
    fingerprint: ProxyHostFingerprint = ProxyHostFingerprint.none
    allowinsecure: Union[bool, None] = None
    is_disabled: Union[bool, None] = None
    mux_enable: Union[bool, None] = None
    fragment_setting: Optional[str] = Field(None, nullable=True)
    noise_setting: Optional[str] = Field(None, nullable=True)
    random_user_agent: Union[bool, None] = None
    use_sni_as_host: Union[bool, None] = None
    model_config = ConfigDict(from_attributes=True)

    @field_validator("remark", mode="after")
    def validate_remark(cls, v):
        try:
            v.format_map(FormatVariables())
        except ValueError as exc:
            raise ValueError("Invalid formatting variables")

        return v

    @field_validator("address", mode="after")
    def validate_address(cls, v):
        try:
            v.format_map(FormatVariables())
        except ValueError as exc:
            raise ValueError("Invalid formatting variables")

        return v

    @field_validator("fragment_setting", check_fields=False)
    @classmethod
    def validate_fragment(cls, v):
        if v and not FRAGMENT_PATTERN.match(v):
            raise ValueError(
                "Fragment setting must be like this: length,interval,packet (10-100,100-200,tlshello)."
            )
        return v

    @field_validator("noise_setting", check_fields=False)
    @classmethod
    def validate_noise(cls, v):
        if v:
            if not NOISE_PATTERN.match(v):
                raise ValueError(
                    "Noise setting must be like this: packet,delay (rand:10-20,100-200)."
                )
            if len(v) > 2000:
                raise ValueError(
                    "Noise can't be longer that 2000 character"
                )
        return v


class ProxyInbound(BaseModel):
    tag: str
    protocol: ProxyTypes
    network: str
    tls: str
    port: Union[int, str]
    ss_method: Optional[str] = None
