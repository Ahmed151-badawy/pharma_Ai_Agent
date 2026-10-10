"""Audit trail: who did what, when (stored in the audit_logs table)."""
from fastapi import Request
from sqlalchemy.orm import Session

from app.logging_conf import request_id_var
from app.models import AuditLog, User


def record(session: Session, action: str, user: User | None = None, detail: dict | None = None,
           request: Request | None = None, username: str | None = None) -> None:
    session.add(
        AuditLog(
            user_id=user.id if user else None,
            username=user.username if user else username,
            action=action,
            detail=detail or {},
            request_id=request_id_var.get(),
            ip=(request.client.host if request and request.client else None),
        )
    )
    session.commit()
