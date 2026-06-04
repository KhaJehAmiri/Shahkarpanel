import time
import jwt
from base64 import b64decode, b64encode
from datetime import datetime, timedelta
from functools import lru_cache
from hashlib import sha256
from math import ceil
from typing import Union


from config import JWT_ACCESS_TOKEN_EXPIRE_MINUTES


@lru_cache(maxsize=None)
def get_secret_key():
    from app.db import GetDB, get_jwt_secret_key
    with GetDB() as db:
        return get_jwt_secret_key(db)


def clear_secret_key_cache() -> None:
    """Invalidate cached JWT secret after rotation (call from admin tooling)."""
    get_secret_key.cache_clear()


_SUBSCRIPTION_SIG_LEN = 22
_LEGACY_SUBSCRIPTION_SIG_LEN = 10


def _subscription_signature(data_b64_str: str, length: int = _SUBSCRIPTION_SIG_LEN) -> str:
    return b64encode(
        sha256((data_b64_str + get_secret_key()).encode("utf-8")).digest(),
        altchars=b"-_",
    ).decode("utf-8")[:length]


def create_admin_token(username: str, is_sudo=False) -> str:
    data = {"sub": username, "access": "sudo" if is_sudo else "admin", "iat": datetime.utcnow()}
    if JWT_ACCESS_TOKEN_EXPIRE_MINUTES > 0:
        expire = datetime.utcnow() + timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
        data["exp"] = expire
    encoded_jwt = jwt.encode(data, get_secret_key(), algorithm="HS256")
    return encoded_jwt


def get_admin_payload(token: str) -> Union[dict, None]:
    try:
        payload = jwt.decode(token, get_secret_key(), algorithms=["HS256"])
        username: str = payload.get("sub")
        access: str = payload.get("access")
        if not username or access not in ('admin', 'sudo'):
            return
        try:
            created_at = datetime.utcfromtimestamp(payload['iat'])
        except KeyError:
            created_at = None

        return {"username": username, "is_sudo": access == "sudo", "created_at": created_at}
    except jwt.exceptions.PyJWTError:
        return


def create_subscription_token(username: str) -> str:
    data = username + ',' + str(ceil(time.time()))
    data_b64_str = b64encode(data.encode('utf-8'), altchars=b'-_').decode('utf-8').rstrip('=')
    data_final = data_b64_str + _subscription_signature(data_b64_str)
    return data_final


def get_subscription_payload(token: str) -> Union[dict, None]:
    try:
        if len(token) < 15:
            return

        if token.startswith("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."):
            payload = jwt.decode(token, get_secret_key(), algorithms=["HS256"])
            if payload.get("access") == "subscription":
                return {"username": payload['sub'], "created_at": datetime.utcfromtimestamp(payload['iat'])}
            else:
                return
        else:
            for sig_len in (_SUBSCRIPTION_SIG_LEN, _LEGACY_SUBSCRIPTION_SIG_LEN):
                if len(token) < sig_len + 5:
                    continue
                u_token = token[:-sig_len]
                u_signature = token[-sig_len:]
                try:
                    u_token_dec = b64decode(
                        (u_token.encode("utf-8") + b"=" * (-len(u_token.encode("utf-8")) % 4)),
                        altchars=b"-_",
                        validate=True,
                    )
                    u_token_dec_str = u_token_dec.decode("utf-8")
                except Exception:
                    continue
                if u_signature == _subscription_signature(u_token, sig_len):
                    parts = u_token_dec_str.split(",", 1)
                    if len(parts) != 2:
                        continue
                    u_username, ts = parts[0], parts[1]
                    return {
                        "username": u_username,
                        "created_at": datetime.utcfromtimestamp(int(ts)),
                    }
            return
    except jwt.exceptions.PyJWTError:
        return
