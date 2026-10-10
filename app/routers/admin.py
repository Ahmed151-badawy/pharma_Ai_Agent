from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_role
from app.db import get_session
from app.models import AuditLog, User

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/audit")
def audit_log(limit: int = Query(100, ge=1, le=500), action: str | None = None,
              _: User = Depends(require_role("admin")), session: Session = Depends(get_session)):
    """Most recent audit entries (who did what, when)."""
    query = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if action:
        query = query.where(AuditLog.action == action)
    return [
        {"id": r.id, "ts": r.ts, "user": r.username, "action": r.action, "detail": r.detail,
         "request_id": r.request_id, "ip": r.ip}
        for r in session.scalars(query)
    ]
