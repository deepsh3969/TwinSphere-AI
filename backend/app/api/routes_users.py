"""Phase 10 §17 — ADMIN-only user administration.

Every endpoint requires the ``manage`` permission (ADMIN only, docs/RBAC.md),
is rate-limited under the ``admin`` category and is written to the audit log.
Password hashes are never returned and the admin-set temporary password is
shown exactly once in the response.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.audit import audit, request_meta
from app.core.database import get_db
from app.core.ratelimit import check as rate_check
from app.core.ratelimit import client_ip
from app.core.security import ROLES, hash_password, require, revoke_all_tokens, validate_password
from app.models.entities import User
from app.schemas.common import UserCreate, UserUpdate

router = APIRouter(prefix="/api/users", tags=["users"])

_MAX_PAGE = 100


def _profile(user: User) -> dict:
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


def _active_admins(db: Session) -> int:
    return db.query(User).filter(User.role == "ADMIN", User.is_active.is_(True)).count()


@router.get("")
def list_users(
    q: str | None = Query(None, max_length=64),
    role: str | None = Query(None, max_length=16),
    active: bool | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=_MAX_PAGE),
    principal: dict = Depends(require("manage")),
    request: Request = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
):
    rate_check("admin", client_ip(request))
    query = db.query(User)
    if q:
        like = f"%{q.strip().lower()}%"
        query = query.filter((User.username.ilike(like)) | (User.email.ilike(like)))
    if role:
        if role.upper() not in ROLES:
            raise HTTPException(400, f"Unknown role — expected one of {', '.join(ROLES)}")
        query = query.filter(User.role == role.upper())
    if active is not None:
        query = query.filter(User.is_active.is_(active))
    total = query.count()
    users = query.order_by(User.username).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "users": [_profile(u) for u in users],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, -(-total // page_size)),
        "active_admins": _active_admins(db),
    }


@router.post("", status_code=201)
def create_user(
    body: UserCreate,
    request: Request,
    principal: dict = Depends(require("manage")),
    db: Session = Depends(get_db),
):
    rate_check("admin", client_ip(request))
    ip, rid = request_meta(request)
    username = body.username.strip().lower()
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(409, "Username already exists")
    if db.query(User).filter(User.email == body.email.strip().lower()).first():
        raise HTTPException(409, "Email already exists")
    validate_password(body.password, username)

    user = User(
        id=f"u_{uuid.uuid4().hex[:10]}",
        username=username,
        email=body.email.strip().lower(),
        password_hash=hash_password(body.password),
        role=body.role,
        password_changed_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.commit()
    audit(db, "admin.user_create", actor=principal.get("username", "admin"),
          detail=f"Created {body.role} user {username}", user_id=principal.get("sub"),
          entity_type="user", entity_id=user.id, ip_address=ip, request_id=rid)
    return {"user": _profile(user)}


@router.patch("/{user_id}")
def update_user(
    user_id: str,
    body: UserUpdate,
    request: Request,
    principal: dict = Depends(require("manage")),
    db: Session = Depends(get_db),
):
    """Change role and/or activation state (Phase 10 §17).

    Protects against lock-out: the last active ADMIN can neither be demoted
    nor disabled, and an admin cannot disable themselves.
    """
    rate_check("admin", client_ip(request))
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    ip, rid = request_meta(request)
    actor = principal.get("username", "admin")

    if body.role is not None and body.role != user.role:
        if user.role == "ADMIN" and body.role != "ADMIN" and _active_admins(db) <= 1:
            raise HTTPException(409, "Cannot demote the last active administrator")
        old_role, user.role = user.role, body.role
        audit(db, "admin.role_change", actor=actor,
              detail=f"{user.username}: {old_role} → {body.role}", user_id=principal.get("sub"),
              entity_type="user", entity_id=user.id, ip_address=ip, request_id=rid)

    if body.is_active is not None and body.is_active != user.is_active:
        if user.id == principal.get("sub"):
            raise HTTPException(409, "Cannot change your own active state")
        if user.role == "ADMIN" and not body.is_active and _active_admins(db) <= 1:
            raise HTTPException(409, "Cannot disable the last active administrator")
        user.is_active = body.is_active
        revoke_all_tokens(db, user)  # disabled accounts lose all sessions immediately
        audit(db, "admin.user_disable" if not body.is_active else "admin.user_enable",
              actor=actor, detail=f"{user.username} {'disabled' if not body.is_active else 'enabled'}",
              user_id=principal.get("sub"), entity_type="user", entity_id=user.id,
              ip_address=ip, request_id=rid)

    db.add(user)
    db.commit()
    return {"user": _profile(user), "active_admins": _active_admins(db)}


@router.post("/{user_id}/reset-password")
def reset_user_password(
    user_id: str,
    request: Request,
    password: str | None = Query(None, min_length=8, max_length=128),
    principal: dict = Depends(require("manage")),
    db: Session = Depends(get_db),
):
    """Administrative password reset (local reset flow — Phase 10 §6/§17).

    Sets a one-time password (generated when not supplied), revokes every
    outstanding session for the target account and audits the change.  The
    password is returned exactly once and never logged.
    """
    rate_check("admin", client_ip(request))
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    ip, rid = request_meta(request)

    import secrets as _secrets

    temporary = password or _secrets.token_urlsafe(12)
    validate_password(temporary, user.username)
    user.password_hash = hash_password(temporary)
    user.password_changed_at = datetime.now(timezone.utc)
    revoke_all_tokens(db, user)
    db.add(user)
    db.commit()
    audit(db, "admin.password_reset", actor=principal.get("username", "admin"),
          detail=f"Password reset for {user.username}; sessions revoked",
          user_id=principal.get("sub"), entity_type="user", entity_id=user.id,
          ip_address=ip, request_id=rid)
    return {"ok": True, "temporary_password": temporary, "user": _profile(user)}
