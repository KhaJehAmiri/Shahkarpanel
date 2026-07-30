import time
import jwt
from base64 import b64decode, b64encode
from datetime import datetime, timedelta
from functools import lru_cache
from hashlib import sha256
from typing import Union


from config import JWT_ACCESS_TOKEN_EXPIRE_MINUTES, JWT_REFRESH_TOKEN_EXPIRE_DAYS


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


def create_admin_refresh_token(username: str, is_sudo: bool = False) -> str:
    """Long-lived refresh token for the admin dashboard (L6)."""
    data = {
        "sub": username,
        "access": "admin_refresh",
        "sudo": bool(is_sudo),
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(days=JWT_REFRESH_TOKEN_EXPIRE_DAYS),
    }
    return jwt.encode(data, get_secret_key(), algorithm="HS256")


def admin_token_bundle(username: str, is_sudo: bool = False) -> dict:
    """Access + refresh pair for admin/SSO login responses."""
    return {
        "access_token": create_admin_token(username, is_sudo),
        "refresh_token": create_admin_refresh_token(username, is_sudo),
        "expires_in": app_access_token_expires_in(),
    }


def create_portal_token(username: str) -> str:
    data = {"sub": username, "access": "portal", "iat": datetime.utcnow()}
    if JWT_ACCESS_TOKEN_EXPIRE_MINUTES > 0:
        expire = datetime.utcnow() + timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
        data["exp"] = expire
    return jwt.encode(data, get_secret_key(), algorithm="HS256")


def get_admin_payload(token: str) -> Union[dict, None]:
    try:
        payload = jwt.decode(token, get_secret_key(), algorithms=["HS256"])
        username: str = payload.get("sub")
        access: str = payload.get("access")
        if not username or access not in ('admin', 'sudo'):
            return
        try:
            created_at = datetime.utcfromtimestamp(payload['iat'])
            iat = float(payload['iat'])
        except KeyError:
            created_at = None
            iat = None

        from app.utils.admin_sessions import is_token_revoked

        if is_token_revoked(username, iat):
            return

        return {"username": username, "is_sudo": access == "sudo", "created_at": created_at, "iat": iat}
    except jwt.exceptions.PyJWTError:
        return


def get_admin_refresh_payload(token: str) -> Union[dict, None]:
    try:
        payload = jwt.decode(token, get_secret_key(), algorithms=["HS256"])
        username: str = payload.get("sub")
        if not username or payload.get("access") != "admin_refresh":
            return
        try:
            iat = float(payload["iat"])
        except (KeyError, TypeError, ValueError):
            iat = None

        from app.utils.admin_sessions import is_token_revoked

        if is_token_revoked(username, iat):
            return

        return {
            "username": username,
            "is_sudo": bool(payload.get("sudo")),
            "iat": iat,
        }
    except jwt.exceptions.PyJWTError:
        return


APP_REFRESH_TOKEN_EXPIRE_DAYS = 30


def create_app_access_token(username: str) -> str:
    """Short-lived access token for the SigmaGuard mobile/desktop client."""
    data = {"sub": username, "access": "app", "iat": datetime.utcnow()}
    if JWT_ACCESS_TOKEN_EXPIRE_MINUTES > 0:
        data["exp"] = datetime.utcnow() + timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(data, get_secret_key(), algorithm="HS256")


def create_app_refresh_token(username: str) -> str:
    """Long-lived refresh token (30-day cycle) for the client app."""
    data = {
        "sub": username,
        "access": "app_refresh",
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(days=APP_REFRESH_TOKEN_EXPIRE_DAYS),
    }
    return jwt.encode(data, get_secret_key(), algorithm="HS256")


def app_access_token_expires_in() -> Union[int, None]:
    """Access-token lifetime in seconds, or ``None`` when tokens never expire."""
    if JWT_ACCESS_TOKEN_EXPIRE_MINUTES > 0:
        return JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
    return None


def get_app_payload(token: str) -> Union[dict, None]:
    try:
        payload = jwt.decode(token, get_secret_key(), algorithms=["HS256"])
        username = payload.get("sub")
        if not username or payload.get("access") != "app":
            return
        return {"username": username}
    except jwt.exceptions.PyJWTError:
        return


def get_app_refresh_payload(token: str) -> Union[dict, None]:
    try:
        payload = jwt.decode(token, get_secret_key(), algorithms=["HS256"])
        username = payload.get("sub")
        if not username or payload.get("access") != "app_refresh":
            return
        return {"username": username}
    except jwt.exceptions.PyJWTError:
        return


def get_portal_payload(token: str) -> Union[dict, None]:
    try:
        payload = jwt.decode(token, get_secret_key(), algorithms=["HS256"])
        username: str = payload.get("sub")
        access: str = payload.get("access")
        if not username or access != "portal":
            return
        try:
            created_at = datetime.utcfromtimestamp(payload['iat'])
            iat = float(payload['iat'])
        except KeyError:
            created_at = None
            iat = None
        return {"username": username, "created_at": created_at, "iat": iat}
    except jwt.exceptions.PyJWTError:
        return


def create_subscription_token(username: str, *, issued_at: int | None = None) -> str:
    """Build a signed subscription token. ``issued_at=0`` = stable per-user token."""
    ts = 0 if issued_at is None else int(issued_at)
    data = username + "," + str(ts)
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
