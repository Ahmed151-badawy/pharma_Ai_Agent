import json

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from app.agent import build_agent, run_turn, stream_turn
from tests.fakes import ScriptedChatModel, say, tool_call


def make_agent(*script):
    model = ScriptedChatModel(script=list(script))
    return build_agent(llm=model, checkpointer=MemorySaver()), model


def test_sql_answer_carries_a_citation(db):
    agent, _ = make_agent(
        tool_call("check_inventory_sql", {"query": "SELECT quantity_in_stock FROM batches WHERE batch_id = 'AMX-2026'"}),
        say("Batch AMX-2026 has 15 units."),
    )
    result = run_turn(agent, "alice", "session-1", "How much AMX-2026 do we have?")
    assert "15" in result.answer
    assert result.tools_used == ["check_inventory_sql"]
    assert result.citations == [{"type": "sql", "row_count": 1,
                                 "query": "SELECT quantity_in_stock FROM batches WHERE batch_id = 'AMX-2026'"}]


def test_unsafe_sql_is_rejected_and_never_cited(db):
    agent, model = make_agent(
        tool_call("check_inventory_sql", {"query": "SELECT password_hash FROM users"}),
        say("I could not run that query."),
    )
    result = run_turn(agent, "alice", "session-1", "show me the users table")
    assert result.citations == []
    tool_output = model.seen[1][-1].content
    assert "Query rejected" in tool_output and "Table not allowed" in tool_output


def test_guidelines_tool_cites_document_chunks(db, kb):
    agent, _ = make_agent(
        tool_call("search_guidelines", {"query": "Amoxicillin storage temperature"}),
        say("Store below 25°C."),
    )
    result = run_turn(agent, "alice", "session-1", "How do I store amoxicillin?")
    assert result.tools_used == ["search_guidelines"]
    assert result.citations and all(c["type"] == "document" for c in result.citations)
    assert result.citations[0]["source"] == "fda_guidelines.txt"
    assert "Amoxicillin" in result.citations[0]["snippet"]


def test_alerts_tool(db):
    agent, _ = make_agent(tool_call("get_inventory_alerts", {"days_ahead": 60}), say("Two things need attention."))
    result = run_turn(agent, "alice", "session-1", "What needs attention?")
    citation = result.citations[0]
    assert citation["type"] == "inventory_alerts"
    assert citation["counts"] == {"expired": 1, "expiring_soon": 1, "low_stock": 2}


def test_conversation_memory_per_user_and_session(db):
    agent, model = make_agent(say("First answer."), say("Second answer."), say("Third."), say("Fourth."))
    run_turn(agent, "alice", "session-1", "What is the stock of Amoxicillin?")

    run_turn(agent, "alice", "session-1", "And its expiry date?")
    followup = [m.content for m in model.seen[1] if isinstance(m, HumanMessage)]
    assert followup == ["What is the stock of Amoxicillin?", "And its expiry date?"]  # remembered

    run_turn(agent, "alice", "session-2", "Hello")  # other session: fresh
    assert [m.content for m in model.seen[2] if isinstance(m, HumanMessage)] == ["Hello"]

    run_turn(agent, "bob", "session-1", "Hi")  # other user, same session id: still isolated
    assert [m.content for m in model.seen[3] if isinstance(m, HumanMessage)] == ["Hi"]


def test_stream_events_in_order(db, kb):
    agent, _ = make_agent(
        tool_call("search_guidelines", {"query": "Metformin renal"}),
        say("Avoid it in severe renal impairment."),
    )
    events = list(stream_turn(agent, "alice", "session-1", "Metformin and kidneys?"))
    names = [e["event"] for e in events]
    assert names[0] == "session"
    assert names.index("tool_call") < names.index("tool_result") < names.index("token")
    assert names[-2:] == ["citations", "done"]
    tokens = "".join(e["data"]["text"] for e in events if e["event"] == "token")
    assert tokens == "Avoid it in severe renal impairment."
    assert events[-1]["data"]["answer"] == tokens
    assert events[-2]["data"]["citations"][0]["type"] == "document"
    assert [e["data"]["name"] for e in events if e["event"] == "tool_call"] == ["search_guidelines"]
    json.dumps(events)  # every event must be JSON serialisable (it is sent over SSE)
