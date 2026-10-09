from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.entities import AuditLog

# Actions that must never carry free-form client data in `detail`.
_SENSITIVE_MARKERS = ("password", "token", "secret", "authorization", "api_key", "apikey")


def _redact(text: str) -> str:
    """Best-effort scrub of credential-looking substrings from audit details."""
    lowered = text.lower()
    for marker in _SENSITIVE_MARKERS:
        if marker in lowered:
            # Never persist the offending line — replace wholesale.
            return "[redacted — sensitive content omitted]"
    return text


def audit(db: Session, action: str, actor: str = "system", entity: str = "", detail: str = "",
          user_id: str | None = None, entity_type: str | None = None,
          entity_id: str | None = None, ip_address: str | None = None,
          outcome: str = "SUCCESS", request_id: str | None = None) -> None:
    """Append a structured audit record (Phase 10 §15).  Append-only by design:
    no application API mutates or deletes these rows."""
    db.add(
        AuditLog(
            action=action,
            actor=actor,
            user_id=user_id or actor,
            entity=entity,
            entity_type=entity_type,
            entity_id=entity_id or (entity or None),
            ip_address=ip_address,
            detail=_redact(detail or ""),
            outcome=outcome or "SUCCESS",
            request_id=request_id,
            created_at=datetime.now(timezone.utc),
        )
    )
    try:
        db.commit()
    except Exception:
        db.rollback()


def request_meta(request) -> tuple[str | None, str | None]:
    """(ip, request_id) helper for endpoints that hold a Request object."""
    if request is None:
        return None, None
    from app.core.ratelimit import client_ip

    rid = getattr(getattr(request, "state", None), "request_id", None)
    return client_ip(request), rid
