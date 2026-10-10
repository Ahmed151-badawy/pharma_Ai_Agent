import json
from datetime import datetime, timedelta, timezone

import pytest
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import text

from app.agent import build_agent
from app.routers.chat import agent_dependency
from tests.conftest import login
from tests.fakes import ScriptedChatModel, say, tool_call


def use_agent(client, *script):
    model = ScriptedChatModel(script=list(script))
    agent = build_agent(llm=model, checkpointer=MemorySaver())
    client.app.dependency_overrides[agent_dependency] = lambda: agent
    return model


# ------------------------------------------------------------------ auth & roles
def test_health_and_ready(client):
    assert client.get("/health").json()["status"] == "healthy"
    ready = client.get("/ready").json()
    assert ready["status"] == "ready" and ready["knowledge_base_chunks"] > 0


def test_request_id_header_is_returned_and_echoed(client):
    assert len(client.get("/health").headers["X-Request-ID"]) >= 8
    assert client.get("/health", headers={"X-Request-ID": "abc-123"}).headers["X-Request-ID"] == "abc-123"


def test_login_success_and_me(client):
    headers = login(client, "admin", "admin-pass-123")
    me = client.get("/api/v1/auth/me", headers=headers).json()
    assert me["username"] == "admin" and me["role"] == "admin"


@pytest.mark.parametrize("username,password", [("admin", "wrong"), ("ghost", "whatever")])
def test_login_failure_is_401_and_audited(client, admin_headers, username, password):
    assert client.post("/api/v1/auth/login", json={"username": username, "password": password}).status_code == 401
    entries = client.get("/api/v1/admin/audit?action=login_failed", headers=admin_headers).json()
    assert entries and entries[0]["user"] == username


def test_missing_and_tampered_tokens_are_rejected(client, admin_headers):
    assert client.get("/api/v1/auth/me").status_code == 401
    bad = {"Authorization": admin_headers["Authorization"][:-3] + "abc"}
    assert client.get("/api/v1/auth/me", headers=bad).status_code == 401


def test_deactivated_user_loses_access_immediately(client, make_user, db):
    headers = make_user("temp", "viewer")
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
    with db.begin() as conn:
        conn.execute(text("UPDATE users SET is_active = false WHERE username = 'temp'"))
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_role_enforcement(client, viewer_headers, pharmacist_headers):
    assert client.get("/api/v1/inventory/alerts", headers=viewer_headers).status_code == 200
    body = {"batch_id": "AMX-2026", "movement_type": "stock_in", "quantity": 5}
    assert client.post("/api/v1/inventory/movements", json=body, headers=viewer_headers).status_code == 403
    assert client.post("/api/v1/inventory/movements", json=body, headers=pharmacist_headers).status_code == 201
    assert client.get("/api/v1/admin/audit", headers=pharmacist_headers).status_code == 403
    assert client.get("/api/v1/auth/users", headers=viewer_headers).status_code == 403


def test_user_creation_validation(client, admin_headers):
    ok = {"username": "newbie", "password": "long-enough-1", "role": "viewer"}
    assert client.post("/api/v1/auth/users", json=ok, headers=admin_headers).status_code == 201
    assert client.post("/api/v1/auth/users", json=ok, headers=admin_headers).status_code == 409
    assert client.post("/api/v1/auth/users", json=ok | {"username": "x y", "password": "short"},
                       headers=admin_headers).status_code == 422
    assert client.post("/api/v1/auth/users", json=ok | {"username": "boss", "role": "root"},
                       headers=admin_headers).status_code == 422


def test_login_rate_limit(client, settings):
    settings.rate_limit_enabled, settings.login_rate_limit_per_minute = True, 3
    try:
        codes = [client.post("/api/v1/auth/login", json={"username": "a", "password": "b"}).status_code
                 for _ in range(5)]
    finally:
        settings.rate_limit_enabled, settings.login_rate_limit_per_minute = False, 10
    assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]


# ------------------------------------------------------------------ chat
def test_chat_requires_login(client):
    assert client.post("/api/v1/chat", json={"query": "hi"}).status_code == 401


def test_chat_returns_answer_session_and_citations_and_is_audited(client, viewer_headers, admin_headers):
    use_agent(client,
              tool_call("check_inventory_sql", {"query": "SELECT quantity_in_stock FROM batches WHERE batch_id = 'AMX-2026'"}),
              say("AMX-2026 has 15 units."))
    body = client.post("/api/v1/chat", json={"query": "stock of AMX-2026?"}, headers=viewer_headers).json()
    assert body["response"] == "AMX-2026 has 15 units."
    assert body["session_id"] and body["tools_used"] == ["check_inventory_sql"]
    assert body["citations"][0]["type"] == "sql"
    audit = client.get("/api/v1/admin/audit?action=chat", headers=admin_headers).json()[0]
    assert audit["user"] == "vic" and audit["detail"]["query"] == "stock of AMX-2026?"


def test_chat_memory_across_requests(client, viewer_headers):
    model = use_agent(client, say("Answer one."), say("Answer two."))
    first = client.post("/api/v1/chat", json={"query": "What is the stock of Amoxicillin?"}, headers=viewer_headers).json()
    client.post("/api/v1/chat", json={"query": "And its expiry date?", "session_id": first["session_id"]},
                headers=viewer_headers)
    humans = [m.content for m in model.seen[1] if m.type == "human"]
    assert humans == ["What is the stock of Amoxicillin?", "And its expiry date?"]


def test_chat_input_validation(client, viewer_headers):
    use_agent(client, say("unused"))  # dependencies are resolved before the body is validated
    assert client.post("/api/v1/chat", json={"query": ""}, headers=viewer_headers).status_code == 422
    assert client.post("/api/v1/chat", json={"query": "x" * 2001}, headers=viewer_headers).status_code == 422
    assert client.post("/api/v1/chat", json={"query": "hi", "session_id": "bad id!"},
                       headers=viewer_headers).status_code == 422


def test_chat_without_groq_key_is_a_clean_503(client, viewer_headers):
    response = client.post("/api/v1/chat", json={"query": "hi"}, headers=viewer_headers)
    assert response.status_code == 503 and "GROQ_API_KEY" in response.json()["detail"]


def test_chat_stream_sse(client, viewer_headers):
    use_agent(client, tool_call("search_guidelines", {"query": "Amoxicillin storage"}), say("Store below 25 degrees."))
    events = []
    with client.stream("POST", "/api/v1/chat/stream", json={"query": "How to store amoxicillin?"},
                       headers=viewer_headers) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        name = None
        for line in response.iter_lines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                events.append((name, json.loads(line[6:])))
    names = [n for n, _ in events]
    assert names[0] == "session" and names[-1] == "done" and "token" in names and "citations" in names
    assert "".join(d["text"] for n, d in events if n == "token") == "Store below 25 degrees."
    assert dict(events)["citations"]["citations"][0]["source"] == "fda_guidelines.txt"


# ------------------------------------------------------------------ inventory
def test_alerts_content(client, viewer_headers):
    data = client.get("/api/v1/inventory/alerts?days=60", headers=viewer_headers).json()
    assert [b["batch_id"] for b in data["expired"]] == ["IBU-1001"]
    assert [b["batch_id"] for b in data["expiring_soon"]] == ["MET-5510"]
    assert {m["medicine"] for m in data["low_stock"]} == {"Amoxicillin", "Metformin"}
    wider = client.get("/api/v1/inventory/alerts?days=120", headers=viewer_headers).json()
    assert {b["batch_id"] for b in wider["expiring_soon"]} == {"MET-5510", "AMX-2026"}
    assert client.get("/api/v1/inventory/alerts?days=0", headers=viewer_headers).status_code == 422


def test_two_step_stock_movement(client, pharmacist_headers):
    pending = client.post("/api/v1/inventory/movements", headers=pharmacist_headers,
                          json={"batch_id": "AMX-2026", "movement_type": "stock_out", "quantity": 5}).json()
    assert "Remove 5 units from batch AMX-2026" in pending["summary"]

    def quantity():
        batches = client.get("/api/v1/inventory/batches", headers=pharmacist_headers).json()
        return next(b["quantity"] for b in batches if b["batch_id"] == "AMX-2026")

    assert quantity() == 15  # nothing changed before confirmation
    done = client.post(f"/api/v1/inventory/movements/{pending['confirmation_token']}/confirm", headers=pharmacist_headers)
    assert done.status_code == 200 and done.json()["new_quantity"] == 10 and quantity() == 10
    again = client.post(f"/api/v1/inventory/movements/{pending['confirmation_token']}/confirm", headers=pharmacist_headers)
    assert again.status_code == 409  # cannot be replayed

    report = client.get("/api/v1/inventory/report/daily", headers=pharmacist_headers).json()
    assert report["movements_today"] == [{"type": "STOCK_OUT", "transactions": 1, "net_units": -5}]
    assert report["totals"]["medicines"] == 3 and report["alert_counts"]["expired"] == 1


def test_movement_rules(client, pharmacist_headers, make_user):
    post = lambda body, headers=pharmacist_headers: client.post(  # noqa: E731
        "/api/v1/inventory/movements", json=body, headers=headers)
    assert post({"batch_id": "AMX-2026", "movement_type": "stock_out", "quantity": 16}).status_code == 409
    assert post({"batch_id": "NOPE", "movement_type": "stock_in", "quantity": 1}).status_code == 404
    assert post({"batch_id": "IBU-1001", "movement_type": "stock_in", "quantity": 1}).status_code == 409  # expired
    assert post({"batch_id": "AMX-2026", "movement_type": "stock_in", "quantity": 0}).status_code == 422

    token = post({"batch_id": "AMX-2026", "movement_type": "stock_in", "quantity": 1}).json()["confirmation_token"]
    other = make_user("pam", "pharmacist")
    assert client.post(f"/api/v1/inventory/movements/{token}/confirm", headers=other).status_code == 404  # not yours


def test_stale_confirmation_is_rejected(client, pharmacist_headers, db):
    body = {"batch_id": "AMX-2026", "movement_type": "stock_out", "quantity": 10}
    token = client.post("/api/v1/inventory/movements", json=body, headers=pharmacist_headers).json()["confirmation_token"]
    with db.begin() as conn:  # token expires
        conn.execute(text("UPDATE pending_actions SET expires_at = :t"),
                     {"t": datetime.now(timezone.utc) - timedelta(minutes=1)})
    assert client.post(f"/api/v1/inventory/movements/{token}/confirm", headers=pharmacist_headers).status_code == 410

    token2 = client.post("/api/v1/inventory/movements", json=body, headers=pharmacist_headers).json()["confirmation_token"]
    with db.begin() as conn:  # stock drops below the requested amount before confirmation
        conn.execute(text("UPDATE batches SET quantity_in_stock = 3 WHERE batch_id = 'AMX-2026'"))
    assert client.post(f"/api/v1/inventory/movements/{token2}/confirm", headers=pharmacist_headers).status_code == 409


# ------------------------------------------------------------------ documents
def upload(client, headers, name="note.txt", data=b"Zorbaxine tablets must be kept refrigerated at 2-8 degrees."):
    return client.post("/api/v1/documents", headers=headers, files={"file": (name, data, "application/octet-stream")})


def test_document_upload_search_and_delete(client, admin_headers, viewer_headers):
    created = upload(client, admin_headers)
    assert created.status_code == 201 and created.json()["chunks"] == 1
    doc_id = created.json()["id"]

    hits = client.get("/api/v1/documents/search?q=Zorbaxine refrigerated", headers=viewer_headers).json()
    assert hits[0]["source"] == "note.txt" and hits[0]["doc_id"] == doc_id
    assert [d["filename"] for d in client.get("/api/v1/documents", headers=viewer_headers).json()] == ["note.txt"]

    assert client.delete(f"/api/v1/documents/{doc_id}", headers=admin_headers).status_code == 204
    hits = client.get("/api/v1/documents/search?q=Zorbaxine refrigerated", headers=viewer_headers).json()
    assert all(h["doc_id"] != doc_id for h in hits)
    assert client.delete(f"/api/v1/documents/{doc_id}", headers=admin_headers).status_code == 404


def test_document_upload_rules(client, admin_headers, viewer_headers, settings):
    assert upload(client, viewer_headers).status_code == 403
    assert upload(client, admin_headers).status_code == 201
    assert upload(client, admin_headers).status_code == 409  # same content twice
    assert upload(client, admin_headers, "virus.exe", b"x").status_code == 415
    assert upload(client, admin_headers, "fake.pdf", b"not really a pdf").status_code == 422
    settings.max_upload_mb = 0
    try:
        assert upload(client, admin_headers, "big.txt", b"some text").status_code == 413
    finally:
        settings.max_upload_mb = 10


def test_uploaded_document_is_cited_by_the_agent(client, admin_headers, viewer_headers):
    upload(client, admin_headers, "zorbaxine_sop.txt", b"Zorbaxine tablets must be kept refrigerated at 2-8 degrees.")
    use_agent(client, tool_call("search_guidelines", {"query": "Zorbaxine refrigerated"}), say("Keep it at 2-8 degrees."))
    body = client.post("/api/v1/chat", json={"query": "How to store Zorbaxine?"}, headers=viewer_headers).json()
    assert any(c.get("source") == "zorbaxine_sop.txt" for c in body["citations"])


# ------------------------------------------------------------------ audit trail
def test_audit_trail_records_sensitive_actions(client, admin_headers, pharmacist_headers):
    token = client.post("/api/v1/inventory/movements", headers=pharmacist_headers,
                        json={"batch_id": "AMX-2026", "movement_type": "stock_in", "quantity": 2}).json()["confirmation_token"]
    client.post(f"/api/v1/inventory/movements/{token}/confirm", headers=pharmacist_headers)
    upload(client, admin_headers)
    actions = [e["action"] for e in client.get("/api/v1/admin/audit?limit=50", headers=admin_headers).json()]
    for expected in ("login", "user_created", "movement_requested", "movement_confirmed", "document_uploaded"):
        assert expected in actions
