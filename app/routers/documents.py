from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.auth import require_role
from app.config import get_settings
from app.db import get_session
from app.models import Document, User
from app.rag import get_kb, ingest_document
from app.schemas import DocumentOut

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])


@router.get("", response_model=list[DocumentOut])
def list_documents(_: User = Depends(require_role("viewer")), session: Session = Depends(get_session)):
    return session.scalars(select(Document).order_by(Document.created_at.desc())).all()


@router.get("/search")
def search(q: str = Query(min_length=2, max_length=300), _: User = Depends(require_role("viewer"))):
    """Debug / demo endpoint: show what the retrieval layer returns for a query."""
    return [h.citation() for h in get_kb().search(q)]


@router.post("", response_model=DocumentOut, status_code=201)
def upload(request: Request, file: UploadFile = File(...), admin: User = Depends(require_role("admin")),
           session: Session = Depends(get_session)):
    """Upload a PDF / TXT / MD document. It is chunked, embedded and becomes searchable immediately."""
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status_code=413, detail=f"File too large (max {get_settings().max_upload_mb} MB).")
    row = ingest_document(session, get_kb(), file.filename or "document", data, admin.username)
    audit.record(session, "document_uploaded", admin,
                 {"id": row.id, "filename": row.filename, "chunks": row.chunks}, request)
    return row


@router.delete("/{doc_id}", status_code=204)
def delete(doc_id: str, request: Request, admin: User = Depends(require_role("admin")),
           session: Session = Depends(get_session)):
    row = session.get(Document, doc_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    get_kb().delete_document(doc_id)
    session.delete(row)
    session.commit()
    audit.record(session, "document_deleted", admin, {"id": doc_id, "filename": row.filename}, request)
    return Response(status_code=204)
