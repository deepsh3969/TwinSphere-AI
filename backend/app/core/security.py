import hashlib
import hmac
import os
import time
from functools import wraps

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings

_bearer = HTTPBearer(auto_error=False)

ROLES = ["ADMIN", "OPERATOR", "ANALYST", "VIEWER"]

ROLE_PERMISSIONS = {
    "ADMIN": {"read", "simulate", "analyze", "manage", "apply"},
    "OPERATOR": {"read", "simulate", "apply"},
    "ANALYST": {"read", "analyze"},
    "VIEWER": {"read"},
}


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
    return f"pbkdf2${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, hash_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 120_000)
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def create_token(user_id: str, username: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + settings.JWT_EXPIRE_MINUTES * 60,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])


def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    try:
        payload = decode_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    return payload


def require(permission: str):
    def dep(principal: dict = Depends(get_current_principal)) -> dict:
        role = principal.get("role", "VIEWER")
        if permission not in ROLE_PERMISSIONS.get(role, set()):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Role {role} lacks '{permission}' permission")
        return principal

    return dep


_rate_buckets: dict[str, list[float]] = {}


def rate_limit(request: Request) -> None:
    key = f"{request.client.host if request.client else 'anon'}"
    now = time.time()
    bucket = _rate_buckets.setdefault(key, [])
    bucket[:] = [t for t in bucket if now - t < 60]
    if len(bucket) >= settings.RATE_LIMIT_PER_MINUTE:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded")
    bucket.append(now)
