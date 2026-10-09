"""Authentication, password hashing, token and RBAC primitives (Phase 10 hardened).

Design (docs/AUTHENTICATION.md):
* Passwords: Argon2id via ``argon2-cffi`` (legacy PBKDF2 hashes from earlier
  phases remain verifiable so existing accounts keep working).
* Tokens: short-identity HS256 JWTs carrying ``sub/username/role/jti/iss/aud/
  ver`` — signature, expiry, issuer and audience are validated.  The role claim
  is *display metadata only*: effective permissions are always re-read from the
  database on every request, so a demoted/disabled user loses access
  immediately and a token can never grant a role the database does not.
* Revocation: logout deny-lists the token id; password change/disable bumps
  ``users.token_version`` which invalidates every outstanding token for that
  user.
* RBAC: deny-by-default ``require(permission)`` against the central
  ``ROLE_PERMISSIONS`` matrix (docs/RBAC.md).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
import uuid
from datetime import datetime, timezone

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.ratelimit import check as rate_check  # noqa: F401  (re-export)
from app.core.ratelimit import client_ip  # noqa: F401

_bearer = HTTPBearer(auto_error=False)

ROLES = ["ADMIN", "OPERATOR", "ANALYST", "VIEWER"]

# Central permission matrix (Phase 10 §7) — see docs/RBAC.md.
#   read      view dashboards/twin/analytics/history
#   simulate  create + control simulations, incidents, realtime engine
#   apply     route-changing actions, recommendation accept/dismiss, activation
#   analyze   trigger AI analyses
#   export    CSV/JSON data exports
#   reset     reset simulations (OPERATOR restricted to simulation lifecycle)
#   audit     view audit records (ADMIN + authorized operational subset)
#   manage    users, roles, security settings, hard resets (ADMIN only)
ROLE_PERMISSIONS = {
    "ADMIN": {"read", "simulate", "apply", "analyze", "export", "reset", "audit", "manage"},
    "OPERATOR": {"read", "simulate", "apply", "export", "reset", "audit"},
    "ANALYST": {"read", "analyze", "export"},
    "VIEWER": {"read"},
}


# ---------------------------------------------------------------- passwords

try:  # Argon2id — maintained library, memory-hard (Phase 10 §5)
    from argon2 import PasswordHasher
    from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

    _ph = PasswordHasher(time_cost=2, memory_cost=64 * 1024, parallelism=2)
    _HAS_ARGON2 = True
except Exception:  # pragma: no cover - argon2-cffi is a hard requirement
    _HAS_ARGON2 = False
    _ph = None

PBKDF2_ITERATIONS_LEGACY = 120_000  # iteration count used by phase 1-9 hashes


def hash_password(password: str, salt: bytes | None = None) -> str:
    """Hash a password with Argon2id (salt argument kept for API compatibility)."""
    if _HAS_ARGON2:
        return _ph.hash(password)
    salt = salt or os.urandom(16)  # pragma: no cover
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS_LEGACY)
    return f"pbkdf2${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Verify against Argon2id or legacy PBKDF2 storage.  Fails closed."""
    if not stored:
        return False
    if stored.startswith("$argon2"):
        if not _HAS_ARGON2:  # pragma: no cover
            return False
        try:
            return _ph.verify(stored, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError, Exception):
            return False
    try:
        _, salt_hex, hash_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex),
                                 PBKDF2_ITERATIONS_LEGACY)
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def needs_rehash(stored: str) -> bool:
    """True when a legacy PBKDF2 hash should be upgraded on next successful login."""
    return _HAS_ARGON2 and not stored.startswith("$argon2")


def validate_password(password: str, username: str = "") -> None:
    """Password policy for account creation / changes (Phase 10 §4)."""
    if len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    if len(password) > 128:
        raise HTTPException(400, "Password must be at most 128 characters")
    if username and password.strip().lower() == username.strip().lower():
        raise HTTPException(400, "Password must not match the username")
    if password.strip().lower() in {"password", "12345678", "password1", "admin1234"}:
        raise HTTPException(400, "Password is too common — choose something less guessable")


# ------------------------------------------------------------------- tokens

def create_token(user_id: str, username: str, role: str, token_version: int = 0) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,          # display metadata — effective role comes from the DB
        "jti": uuid.uuid4().hex,
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "ver": token_version,
        "iat": now,
        "exp": now + settings.JWT_EXPIRE_MINUTES * 60,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Validate signature, algorithm, expiry, issuer and audience."""
    return jwt.decode(
        token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
        audience=settings.JWT_AUDIENCE,
        issuer=settings.JWT_ISSUER,
        options={"require": ["exp", "iat", "sub"]},
    )


def authenticate_token(token: str, db: Session) -> dict:
    """Validate a bearer token and resolve it to a database-backed principal.

    Shared by the HTTP dependency and the WebSocket handshake (Phase 10 §10).
    Raises HTTPException(401) on any failure with a non-revealing message.
    """
    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")

    from app.models.entities import RevokedToken, User

    user = db.get(User, payload.get("sub", ""))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    if payload.get("ver", 0) != (user.token_version or 0):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    jti = payload.get("jti")
    if jti and db.query(RevokedToken).filter(RevokedToken.jti == jti).first() is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")

    return {
        "sub": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,      # fresh from the DB, never the stale token claim
        "jti": jti,
        "exp": payload.get("exp"),
    }


def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> dict:
    """Resolve the bearer token to a *database-backed* principal (Phase 10 §5).

    The signed identity is verified, then the user row is re-read so that
    disabled accounts, deleted accounts, bumped token versions (password
    change / disable) and logout deny-listed jtis all fail immediately.
    """
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    return authenticate_token(credentials.credentials, db)


def has_permission(principal: dict, permission: str) -> bool:
    role = principal.get("role", "VIEWER")
    return permission in ROLE_PERMISSIONS.get(role, set())


def require(permission: str):
    """Deny-by-default authorization dependency (401 unauthenticated / 403 forbidden)."""

    def dep(
        principal: dict = Depends(get_current_principal),
        db: Session = Depends(get_db),
        request: Request = None,  # type: ignore[assignment]
    ) -> dict:
        if not has_permission(principal, permission):
            _audit_denied(db, principal, permission, request)
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Role {principal.get('role', 'VIEWER')} lacks '{permission}' permission",
            )
        return principal

    return dep


def _audit_denied(db: Session, principal: dict, permission: str, request) -> None:
    """Best-effort audit of authorization denials (Phase 10 §15/§21)."""
    try:
        from app.core.audit import audit

        ip = client_ip(request) if request is not None else None
        rid = getattr(getattr(request, "state", None), "request_id", None) if request else None
        audit(db, "authz.denied", actor=principal.get("username", "unknown"),
              detail=f"Missing '{permission}' permission", outcome="DENIED",
              user_id=principal.get("sub"), ip_address=ip, request_id=rid)
    except Exception:  # pragma: no cover — never fail the request because of audit
        pass


def revoke_token(db: Session, principal: dict) -> None:
    """Server-side logout: deny-list this token id until it expires."""
    from app.models.entities import RevokedToken

    jti = principal.get("jti")
    if not jti:
        return
    exp = principal.get("exp")
    try:
        expires_at = datetime.fromtimestamp(exp, tz=timezone.utc) if exp else None
    except Exception:  # pragma: no cover
        expires_at = None
    if db.query(RevokedToken).filter(RevokedToken.jti == jti).first() is None:
        db.add(RevokedToken(id=uuid.uuid4().hex, jti=jti,
                            user_id=principal.get("sub"), expires_at=expires_at))
        db.commit()


def revoke_all_tokens(db: Session, user) -> None:
    """Invalidate every outstanding token for *user* (password change / disable)."""
    user.token_version = (user.token_version or 0) + 1
    db.add(user)


def rate_limit(request: Request, category: str = "general") -> None:
    """Backwards-compatible dependency (Phase ≤9 call sites)."""
    rate_check(category, client_ip(request))


def reset_rate_limits() -> None:
    from app.core.ratelimit import reset

    reset()
