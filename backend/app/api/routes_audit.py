"""Phase 10 §15/§16 — read-only audit log query API.

Access requires the ``audit`` permission (ADMIN; OPERATOR receives the
operational subset — authentication/authorization/administrative actions are
ADMIN-only).  There are deliberately **no** create/update/delete endpoints:
records are append-only through the application.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import has_permission, require
from app.models.entities import AuditLog

router = APIRouter(prefix="/api/audit", tags=["audit"])

# Actions only an ADMIN may see (auth, authz and admin surface).
_ADMIN_ONLY_PREFIXES = ("auth.", "authz.", "admin.")


def _record(row: AuditLog) -> dict:
    return {
        "id": row.id,
        "action": row.action,
        "actor": row.actor,
        "user_id": row.user_id,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "detail": row.detail,
        "outcome": row.outcome or "SUCCESS",
        "ip_address": row.ip_address,
        "request_id": row.request_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _parse_dt(value: str | None, default: datetime | None = None) -> datetime | None:
    if not value:
        return default
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, "Invalid datetime — expected ISO-8601")


@router.get("")
def list_audit(
    q: str | None = Query(None, max_length=64),
    actor: str | None = Query(None, max_length=64),
    action: str | None = Query(None, max_length=60),
    outcome: str | None = Query(None, max_length=16),
    entity_id: str | None = Query(None, max_length=60),
    start: str | None = Query(None),
    end: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    principal: dict = Depends(require("audit")),
    db: Session = Depends(get_db),
):
    start_dt = _parse_dt(start, datetime.utcnow() - timedelta(days=7))
    end_dt = _parse_dt(end, datetime.utcnow() + timedelta(days=1))
    if start_dt and end_dt and end_dt <= start_dt:
        raise HTTPException(400, "end must be after start")

    query = db.query(AuditLog)
    if start_dt:
        query = query.filter(AuditLog.created_at >= start_dt)
    if end_dt:
        query = query.filter(AuditLog.created_at <= end_dt)
    if actor:
        query = query.filter(AuditLog.actor == actor.strip().lower())
    if action:
        query = query.filter(AuditLog.action == action.strip())
    if outcome:
        query = query.filter(AuditLog.outcome == outcome.strip().upper())
    if entity_id:
        query = query.filter(AuditLog.entity_id == entity_id.strip())
    if q:
        like = f"%{q.strip()}%"
        query = query.filter((AuditLog.detail.ilike(like)) | (AuditLog.action.ilike(like)))

    if not has_permission(principal, "manage"):
        # Authorized operational subset: no auth/authz/admin internals (§7).
        from sqlalchemy import or_

        query = query.filter(
            ~or_(*[AuditLog.action.like(f"{p}%") for p in _ADMIN_ONLY_PREFIXES])
        )

    total = query.count()
    rows = query.order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "records": [_record(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, -(-total // page_size)),
        "scope": "full" if has_permission(principal, "manage") else "operational",
    }


@router.get("/actions")
def audit_actions(principal: dict = Depends(require("audit")), db: Session = Depends(get_db)):
    """Distinct action names + actors for filter dropdowns (safe metadata)."""
    query = db.query(AuditLog.action, AuditLog.actor)
    if not has_permission(principal, "manage"):
        from sqlalchemy import or_

        query = query.filter(
            ~or_(*[AuditLog.action.like(f"{p}%") for p in _ADMIN_ONLY_PREFIXES])
        )
    actions = sorted({a for a, _ in query.all()})
    actors = sorted({a for _, a in query.all() if a})
    return {"actions": actions, "actors": actors, "outcomes": ["SUCCESS", "DENIED"]}
