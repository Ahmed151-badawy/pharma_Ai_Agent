"""LangGraph ReAct agent with: three tools, per-session memory, source citations and token streaming."""
import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

from langchain_core.messages import AIMessage, AIMessageChunk, SystemMessage, ToolMessage, trim_messages
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import GraphRecursionError
from langgraph.prebuilt import create_react_agent
from sqlalchemy import text

from app import inventory
from app.config import get_settings
from app.db import SessionLocal, get_readonly_engine
from app.rag import get_kb
from app.sql_guard import UnsafeQueryError, validate_select

logger = logging.getLogger(__name__)
MAX_ROWS = 50

SYSTEM_PROMPT = (
    "You are an expert Pharmaceutical Assistant AI for a pharmacy's operations team. "
    "Use the tools to answer: SQL for stock, batches and expiry; the guidelines search for storage, "
    "contraindications and interactions; the alerts tool for expiring batches and low stock. "
    "Never invent stock counts, expiry dates or drug interactions. If the tools return nothing relevant, say so. "
    "Mention batch ids and document sources you relied on. "
    "You provide operational information only and are not a substitute for a pharmacist's or physician's judgment."
)


# ------------------------------------------------------------------ tools
# Each tool returns (text for the LLM, artifact for us). The artifact carries the citations.
@tool(response_format="content_and_artifact")
def check_inventory_sql(query: str) -> tuple[str, dict]:
    """Run ONE read-only SQL SELECT against the pharmacy inventory database.
    Use it for stock levels, batch numbers, suppliers, expiration dates and stock movements.

    Tables:
      medicines(medicine_id, generic_name, brand_name, category, minimum_stock_level, storage_requirements)
      batches(batch_id, medicine_id, supplier_name, quantity_in_stock, production_date, expiration_date, status)
      inventory_logs(log_id, batch_id, transaction_type, quantity_changed, transaction_date, handled_by)
    batches.medicine_id references medicines.medicine_id. Use CURRENT_DATE for today's date.
    Input must be a single SELECT statement without comments.
    """
    try:
        safe_query = validate_select(query)
    except UnsafeQueryError as exc:
        logger.warning("Rejected SQL from agent: %r (%s)", query, exc)
        return f"Query rejected: {exc}", {"citations": []}

    try:
        with get_readonly_engine().connect() as conn:
            result = conn.execute(text(safe_query))
            columns = list(result.keys())
            rows = result.fetchmany(MAX_ROWS)
    except Exception as exc:
        logger.exception("SQL tool database error")
        return f"Database Error: {exc}", {"citations": []}

    content = f"Columns: {columns}\nRows ({len(rows)}): {[list(r) for r in rows]}"
    citation = {"type": "sql", "query": safe_query, "row_count": len(rows)}
    return content, {"citations": [citation]}


@tool(response_format="content_and_artifact")
def search_guidelines(query: str) -> tuple[str, dict]:
    """Search the knowledge base of storage requirements, contraindications, drug interactions and any
    uploaded documents (labels, SOPs). Input is a natural-language search query."""
    hits = get_kb().search(query)
    if not hits:
        return "No relevant passages found.", {"citations": []}
    blocks = [f"[{h.source}{f', page {h.page}' if h.page else ''}] {h.text}" for h in hits]
    return "\n---\n".join(blocks), {"citations": [h.citation() for h in hits]}


@tool(response_format="content_and_artifact")
def get_inventory_alerts(days_ahead: int = 60) -> tuple[str, dict]:
    """List expired batches, batches expiring within `days_ahead` days, and medicines below their
    minimum stock level. Use it for questions like 'what needs attention' or 'what expires soon'."""
    days = max(1, min(int(days_ahead), 365))
    with SessionLocal() as session:
        data = inventory.get_alerts(session, days=days)
    counts = {k: len(data[k]) for k in ("expired", "expiring_soon", "low_stock")}
    citation = {"type": "inventory_alerts", "as_of": data["as_of"], "days_ahead": days, "counts": counts}
    return json.dumps(data), {"citations": [citation]}


TOOLS = [check_inventory_sql, search_guidelines, get_inventory_alerts]


# ------------------------------------------------------------------ agent construction
def _prompt(state: dict) -> list:
    """System prompt + a bounded window of the conversation (keeps long chats within the context size)."""
    messages = state["messages"]
    trimmed = trim_messages(messages, strategy="last", token_counter=len,
                            max_tokens=get_settings().history_max_messages, start_on="human", include_system=False)
    system = SystemMessage(f"{SYSTEM_PROMPT} Today's date is {date.today().isoformat()}.")
    return [system, *(trimmed or messages[-6:])]


def build_agent(llm=None, checkpointer=None):
    if llm is None:
        from langchain_groq import ChatGroq

        settings = get_settings()
        if not settings.groq_api_key:
            raise RuntimeError("GROQ_API_KEY is not set.")
        llm = ChatGroq(model=settings.groq_model, temperature=0, api_key=settings.groq_api_key)
    # MemorySaver keeps conversations in this process' RAM. For several containers / restarts use a
    # persistent checkpointer (langgraph-checkpoint-postgres) instead.
    return create_react_agent(llm, TOOLS, prompt=_prompt, checkpointer=checkpointer or MemorySaver())


@lru_cache
def get_agent():
    return build_agent()


# ------------------------------------------------------------------ running a turn
@dataclass
class TurnResult:
    answer: str
    citations: list[dict]
    tools_used: list[str]


def _as_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return str(content or "")


def _config(username: str, session_id: str) -> dict:
    # thread id includes the username: one user can never read another user's conversation
    return {"configurable": {"thread_id": f"{username}:{session_id}"},
            "recursion_limit": get_settings().agent_recursion_limit}


def _dedupe(citations: list[dict]) -> list[dict]:
    seen, out = set(), []
    for c in citations:
        key = json.dumps(c, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


LIMIT_MESSAGE = ("I couldn't finish that within the allowed number of steps. "
                 "Please rephrase or split it into smaller questions.")


def run_turn(agent, username: str, session_id: str, query: str) -> TurnResult:
    try:
        state = agent.invoke({"messages": [("user", query)]}, config=_config(username, session_id))
    except GraphRecursionError:
        return TurnResult(LIMIT_MESSAGE, [], [])

    messages = state["messages"]
    last_human = max((i for i, m in enumerate(messages) if m.type == "human"), default=0)
    turn = messages[last_human + 1:]

    citations, tools_used = [], []
    for m in turn:
        if isinstance(m, ToolMessage):
            tools_used.append(m.name)
            if isinstance(m.artifact, dict):
                citations.extend(m.artifact.get("citations", []))
    answer = next((_as_text(m.content) for m in reversed(turn) if isinstance(m, AIMessage) and m.content), "")
    return TurnResult(answer or "The agent produced no final answer.", _dedupe(citations), list(dict.fromkeys(tools_used)))


def stream_turn(agent, username: str, session_id: str, query: str) -> Iterator[dict]:
    """Yield server-sent-event dicts: session, tool_call, tool_result, token, citations, done / error."""
    yield {"event": "session", "data": {"session_id": session_id}}
    citations: list[dict] = []
    tools_used: list[str] = []
    parts: list[str] = []
    try:
        for chunk, _meta in agent.stream({"messages": [("user", query)]}, config=_config(username, session_id),
                                         stream_mode="messages"):
            if isinstance(chunk, ToolMessage):
                tools_used.append(chunk.name)
                if isinstance(chunk.artifact, dict):
                    citations.extend(chunk.artifact.get("citations", []))
                yield {"event": "tool_result", "data": {"name": chunk.name}}
            elif isinstance(chunk, AIMessageChunk):
                for call in chunk.tool_call_chunks or []:
                    if call.get("name"):
                        yield {"event": "tool_call", "data": {"name": call["name"]}}
                piece = _as_text(chunk.content)
                if piece and not chunk.tool_call_chunks:
                    parts.append(piece)
                    yield {"event": "token", "data": {"text": piece}}
    except GraphRecursionError:
        yield {"event": "token", "data": {"text": LIMIT_MESSAGE}}
        parts.append(LIMIT_MESSAGE)
    except Exception:
        logger.exception("Streaming agent error")
        yield {"event": "error", "data": {"detail": "Agent processing error. Check server logs."}}
        return
    yield {"event": "citations", "data": {"citations": _dedupe(citations)}}
    yield {"event": "done", "data": {"tools_used": list(dict.fromkeys(tools_used)), "answer": "".join(parts)}}
