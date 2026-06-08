from abc import ABC, abstractmethod 
from enum import Enum
from uuid import UUID

from pydantic import BaseModel

from ..proto.common.serial.typed_message_pb2 import TypedMessage
from ..proto.proxy.shadowsocks.config_pb2 import \
    Account as ShadowsocksAccountPb2
from ..proto.proxy.shadowsocks.config_pb2 import \
    CipherType as ShadowsocksCiphers
from ..proto.proxy.trojan.config_pb2 import Account as TrojanAccountPb2
from ..proto.proxy.vless.account_pb2 import Account as VLESSAccountPb2
from ..proto.proxy.vmess.account_pb2 import Account as VMessAccountPb2
from .message import Message


class Account(BaseModel, ABC):
    email: str
    level: int = 0

    @property
    @abstractmethod
    def message(self):
        pass

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self.email}>"


class VMessAccount(Account):
    id: UUID

    @property
    def message(self):
        return Message(VMessAccountPb2(id=str(self.id)))


class XTLSFlows(Enum):
    NONE = ''
    VISION = 'xtls-rprx-vision'


class VLESSAccount(Account):
    id: UUID
    flow: XTLSFlows = XTLSFlows.NONE

    @property
    def message(self):
        return Message(VLESSAccountPb2(id=str(self.id), flow=self.flow.value))


class TrojanAccount(Account):
    password: str
    flow: XTLSFlows = XTLSFlows.NONE

    @property
    def message(self):
        return Message(TrojanAccountPb2(password=self.password))


class ShadowsocksMethods(Enum):
    AES_128_GCM = 'aes-128-gcm'
    AES_256_GCM = 'aes-256-gcm'
    CHACHA20_POLY1305 = 'chacha20-ietf-poly1305'
    # Shadowsocks-2022 (AEAD-2022). These ciphers are NOT in the legacy gRPC
    # CipherType proto, so they cannot be hot-added over the Xray handler API;
    # they are applied through full-config reload instead (see SS2022_METHODS).
    BLAKE3_AES_128_GCM = '2022-blake3-aes-128-gcm'
    BLAKE3_AES_256_GCM = '2022-blake3-aes-256-gcm'
    BLAKE3_CHACHA20_POLY1305 = '2022-blake3-chacha20-poly1305'


# Methods that require Shadowsocks-2022 keying (base64 PSK, fixed length) and
# the config-reload apply path rather than gRPC AddUser.
SS2022_METHODS = {
    ShadowsocksMethods.BLAKE3_AES_128_GCM,
    ShadowsocksMethods.BLAKE3_AES_256_GCM,
    ShadowsocksMethods.BLAKE3_CHACHA20_POLY1305,
}

# Required PSK byte-length per Shadowsocks-2022 cipher.
SS2022_KEY_BYTES = {
    ShadowsocksMethods.BLAKE3_AES_128_GCM: 16,
    ShadowsocksMethods.BLAKE3_AES_256_GCM: 32,
    ShadowsocksMethods.BLAKE3_CHACHA20_POLY1305: 32,
}


def is_ss2022(method) -> bool:
    try:
        m = method if isinstance(method, ShadowsocksMethods) else ShadowsocksMethods(method)
    except ValueError:
        return False
    return m in SS2022_METHODS


class ShadowsocksAccount(Account):
    password: str
    method: ShadowsocksMethods = ShadowsocksMethods.CHACHA20_POLY1305

    @property
    def is_2022(self) -> bool:
        return self.method in SS2022_METHODS

    @property
    def cipher_type(self):
        return self.method.name

    @property
    def message(self):
        if self.is_2022:
            # The legacy CipherType proto has no 2022 entries; these users are
            # provisioned via config reload, never via the AddUser handler.
            raise ValueError(
                "Shadowsocks-2022 accounts cannot be added over the gRPC handler; "
                "they are applied through config reload."
            )
        return Message(ShadowsocksAccountPb2(password=self.password, cipher_type=self.cipher_type))
