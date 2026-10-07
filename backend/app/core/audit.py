from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.entities import AuditLog


def audit(db: Session, action: str, actor: str = "system", entity: str = "", detail: str = "",
          user_id: str | None = None, entity_type: str | None = None,
          entity_id: str | None = None, ip_address: str | None = None) -> None:
    db.add(
        AuditLog(
            action=action,
            actor=actor,
            user_id=user_id or actor,
            entity=entity,
            entity_type=entity_type,
            entity_id=entity_id or (entity or None),
            ip_address=ip_address,
            detail=detail,
            created_at=datetime.now(timezone.utc),
        )
    )
    try:
        db.commit()
    except Exception:
        db.rollback()
