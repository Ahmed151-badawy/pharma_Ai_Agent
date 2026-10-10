import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app import audit
from app.agent import get_agent, run_turn, stream_turn
from app.auth import require_role
from app.db import SessionLocal, get_session
from app.models import User
from app.ratelimit import chat_rate_limit
from app.schemas import ChatRequest, ChatResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["chat"])


def agent_dependency():
    """The compiled agent (overridden in tests with a scripted model)."""
    try:
        return get_agent()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(chat_rate_limit)])
def chat(body: ChatRequest, request: Request, user: User = Depends(require_role("viewer")),
         agent=Depends(agent_dependency), session: Session = Depends(get_session)):
    """Ask the agent a question. Send the returned `session_id` back to continue the conversation."""
    session_id = body.session_id or uuid.uuid4().hex
    try:
        result = run_turn(agent, user.username, session_id, body.query)
    except Exception as exc:
        logger.exception("Agent processing error")
        raise HTTPException(status_code=500, detail="Agent processing error. Check server logs.") from exc
    audit.record(session, "chat", user,
                 {"query": body.query[:500], "session_id": session_id, "tools": result.tools_used,
                  "citations": len(result.citations)}, request)
    return ChatResponse(query=body.query, response=result.answer, session_id=session_id,
                        citations=result.citations, tools_used=result.tools_used)


@router.post("/chat/stream", dependencies=[Depends(chat_rate_limit)])
def chat_stream(body: ChatRequest, request: Request, user: User = Depends(require_role("viewer")),
                agent=Depends(agent_dependency)):
    """Same as /chat but streams Server-Sent Events: session, tool_call, tool_result, token, citations, done."""
    session_id = body.session_id or uuid.uuid4().hex

    def event_stream():
        tools: list[str] = []
        for event in stream_turn(agent, user.username, session_id, body.query):
            if event["event"] == "done":
                tools = event["data"]["tools_used"]
            yield f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"
        with SessionLocal() as session:  # own session: the request-scoped one may already be closed
            audit.record(session, "chat_stream", user,
                         {"query": body.query[:500], "session_id": session_id, "tools": tools}, request)

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
