import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.database import get_db
from app.core.security import (
    ROLES,
    create_token,
    get_current_principal,
    hash_password,
    rate_limit,
    require,
    verify_password,
)
from app.models.entities import User
from app.schemas.common import LoginRequest, RegisterRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    rate_limit(request)
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    if not user.is_active:
        raise HTTPException(403, "Account disabled")
    token = create_token(user.id, user.username, user.role)
    audit(db, "auth.login", actor=user.username, detail="User logged in")
    return {
        "access_token": token, "token_type": "bearer",
        "user": {"id": user.id, "username": user.username, "email": user.email, "role": user.role},
    }


@router.post("/register")
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(409, "Username already exists")
    user = User(
        id=f"u_{uuid.uuid4().hex[:10]}", username=body.username, email=body.email,
        password_hash=hash_password(body.password), role=body.role,
    )
    db.add(user)
    db.commit()
    audit(db, "auth.register", actor=body.username, detail=f"Role {body.role}")
    token = create_token(user.id, user.username, user.role)
    return {
        "access_token": token, "token_type": "bearer",
        "user": {"id": user.id, "username": user.username, "email": user.email, "role": user.role},
    }


@router.get("/me")
def me(principal: dict = Depends(get_current_principal)):
    return principal


@router.get("/roles")
def roles(_: dict = Depends(require("read"))):
    return {"roles": ROLES}
