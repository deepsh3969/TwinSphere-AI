import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.audit import audit, request_meta
from app.core.config import settings
from app.core.database import get_db
from app.core.ratelimit import check as rate_check
from app.core.ratelimit import client_ip
from app.core.security import (
    ROLES,
    create_token,
    get_current_principal,
    hash_password,
    needs_rehash,
    require,
    revoke_token,
    revoke_all_tokens,
    validate_password,
    verify_password,
)
from app.models.entities import User
from app.schemas.common import ChangePasswordRequest, LoginRequest, RegisterRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _profile(user: User) -> dict:
    """Safe user projection — never exposes password hashes or token state."""
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "password_changed_at": (
            user.password_changed_at.isoformat() if user.password_changed_at else None
        ),
    }


@router.post("/login")
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    rid = getattr(request.state, "request_id", None)
    # Two buckets: per-IP (shared) and per-IP+username (targeted) — Phase 10 §11.
    rate_check("login", ip)
    rate_check("login", f"{ip}|{body.username.lower()}")

    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        # Uniform response + audit: same message for unknown user vs wrong password
        # (user-enumeration resistance) and the attempted name never hits the
        # response body.
        audit(db, "auth.login", actor=(body.username or "")[:64], detail="Invalid credentials",
              outcome="DENIED", ip_address=ip, request_id=rid)
        raise HTTPException(401, "Invalid credentials")
    if not user.is_active:
        audit(db, "auth.login", actor=user.username, detail="Account disabled",
              outcome="DENIED", user_id=user.id, ip_address=ip, request_id=rid)
        raise HTTPException(403, "Account disabled")

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    user.last_login_at = datetime.now(timezone.utc)
    db.add(user)
    db.commit()

    token = create_token(user.id, user.username, user.role, token_version=user.token_version or 0)
    audit(db, "auth.login", actor=user.username, detail="User logged in",
          user_id=user.id, ip_address=ip, request_id=rid)
    return {
        "access_token": token, "token_type": "bearer",
        "user": {"id": user.id, "username": user.username, "email": user.email,
                 "role": user.role, "is_active": user.is_active},
    }


@router.post("/register")
def register(body: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    """Self-service registration (development only).

    Phase 10 §4/§9: the requested role is **ignored** — self-registered
    accounts are always VIEWER.  Privileged roles are exclusively an ADMIN
    action via /api/users.  Disabled when REGISTRATION_ENABLED=false.
    """
    if not settings.REGISTRATION_ENABLED:
        raise HTTPException(403, "Self-service registration is disabled")
    ip = client_ip(request)
    rate_check("register", ip)
    rid = getattr(request.state, "request_id", None)

    normalized = body.username.strip().lower()
    exists = db.query(User).filter(User.username == normalized).first()
    if exists:
        raise HTTPException(409, "Username already exists")
    validate_password(body.password, normalized)

    user = User(
        id=f"u_{uuid.uuid4().hex[:10]}", username=normalized, email=body.email.strip().lower(),
        password_hash=hash_password(body.password), role="VIEWER",
        password_changed_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.commit()
    audit(db, "auth.register", actor=normalized, detail="Self-registration as VIEWER",
          user_id=user.id, ip_address=ip, request_id=rid)
    token = create_token(user.id, user.username, user.role, token_version=0)
    return {
        "access_token": token, "token_type": "bearer",
        "user": {"id": user.id, "username": user.username, "email": user.email,
                 "role": user.role, "is_active": True},
    }


@router.post("/logout")
def logout(request: Request, principal: dict = Depends(get_current_principal),
           db: Session = Depends(get_db)):
    """Server-side revocation of the presented token (Phase 10 §5/§18)."""
    revoke_token(db, principal)
    ip, rid = request_meta(request)
    audit(db, "auth.logout", actor=principal.get("username", "unknown"),
          user_id=principal.get("sub"), detail="Token revoked", ip_address=ip, request_id=rid)
    return {"ok": True}


@router.get("/me")
def me(principal: dict = Depends(get_current_principal), db: Session = Depends(get_db)):
    """Current-user profile from the database (never the raw token payload)."""
    user = db.get(User, principal.get("sub", ""))
    if user is None:
        raise HTTPException(401, "Invalid token")
    return _profile(user)


@router.post("/change-password")
def change_password(body: ChangePasswordRequest, request: Request,
                    principal: dict = Depends(get_current_principal),
                    db: Session = Depends(get_db)):
    """Change the caller's password; revokes every outstanding token for the
    account and issues a fresh one so the session continues seamlessly."""
    user = db.get(User, principal.get("sub", ""))
    if user is None or not user.is_active:
        raise HTTPException(401, "Invalid token")
    if not verify_password(body.current_password, user.password_hash):
        ip, rid = request_meta(request)
        audit(db, "auth.password_change", actor=user.username, detail="Wrong current password",
              outcome="DENIED", user_id=user.id, ip_address=ip, request_id=rid)
        raise HTTPException(400, "Current password is incorrect")
    validate_password(body.new_password, user.username)

    ip, rid = request_meta(request)
    user.password_hash = hash_password(body.new_password)
    user.password_changed_at = datetime.now(timezone.utc)
    revoke_all_tokens(db, user)
    db.commit()
    token = create_token(user.id, user.username, user.role, token_version=user.token_version)
    audit(db, "auth.password_change", actor=user.username, detail="Password changed; sessions revoked",
          user_id=user.id, ip_address=ip, request_id=rid)
    return {"ok": True, "access_token": token, "token_type": "bearer"}


@router.get("/demo")
def demo_status():
    """Whether seeded demo accounts exist in this deployment — usernames and
    roles only, never passwords (Phase 10 §6)."""
    return {
        "enabled": settings.DEMO_USERS_ENABLED,
        "registration_enabled": settings.REGISTRATION_ENABLED,
        "users": ([
            {"username": u, "role": r, "desc": d}
            for u, r, d in (
                ("admin", "ADMIN", "Full access"),
                ("operator", "OPERATOR", "Run simulations"),
                ("analyst", "ANALYST", "Analytics + AI"),
                ("viewer", "VIEWER", "Read-only"),
            )
        ] if settings.DEMO_USERS_ENABLED else []),
    }


@router.get("/roles")
def roles(_: dict = Depends(require("read"))):
    return {"roles": ROLES}
