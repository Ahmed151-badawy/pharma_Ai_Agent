"""Streamlit web UI for the Pharma AI Agent: chat (streaming + sources), inventory, documents, stock movements."""
import json
import os
import uuid

import pandas as pd
import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000")
ROLE_RANK = {"viewer": 1, "pharmacist": 2, "admin": 3}

st.set_page_config(page_title="Pharma AI Assistant", page_icon="💊", layout="wide")


# ----------------------------------------------------------------------------- API helpers
def api(method: str, path: str, **kwargs) -> requests.Response:
    headers = {"Authorization": f"Bearer {st.session_state.token}"} if st.session_state.get("token") else {}
    response = requests.request(method, f"{API_URL}{path}", headers=headers, timeout=kwargs.pop("timeout", 30), **kwargs)
    if response.status_code == 401 and st.session_state.get("token"):  # token expired
        logout()
    return response


def logout() -> None:
    for key in ("token", "role", "username", "messages", "session_id", "pending"):
        st.session_state.pop(key, None)
    st.rerun()


def can(minimum: str) -> bool:
    return ROLE_RANK.get(st.session_state.get("role", ""), 0) >= ROLE_RANK[minimum]


def error_text(response: requests.Response) -> str:
    try:
        detail = response.json().get("detail", response.text)
    except ValueError:
        detail = response.text
    return f"{response.status_code}: {detail}"


# ----------------------------------------------------------------------------- login
def login_screen() -> None:
    st.title("💊 Pharma AI Assistant")
    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Sign in"):
            try:
                response = requests.post(f"{API_URL}/api/v1/auth/login",
                                         json={"username": username, "password": password}, timeout=15)
            except requests.RequestException as exc:
                st.error(f"Cannot reach the API at {API_URL}: {exc}")
                return
            if response.status_code == 200:
                data = response.json()
                st.session_state.update(token=data["access_token"], role=data["role"], username=username)
                st.rerun()
            elif response.status_code == 429:
                st.error("Too many attempts. Please wait a minute.")
            else:
                st.error("Invalid username or password.")


# ----------------------------------------------------------------------------- chat
def sse_events(response: requests.Response):
    event = None
    for line in response.iter_lines(decode_unicode=True):
        if line.startswith("event: "):
            event = line[7:]
        elif line.startswith("data: "):
            yield event, json.loads(line[6:])


def render_citations(citations: list[dict]) -> None:
    if not citations:
        return
    with st.expander(f"Sources ({len(citations)})"):
        for c in citations:
            if c["type"] == "sql":
                st.caption(f"Database query · {c['row_count']} row(s)")
                st.code(c["query"], language="sql")
            elif c["type"] == "document":
                page = f" · page {c['page']}" if c.get("page") else ""
                st.caption(f"📄 {c['source']}{page}")
                st.markdown(f"> {c['snippet']}")
            elif c["type"] == "inventory_alerts":
                st.caption(f"Inventory alerts · next {c['days_ahead']} days · {c['counts']}")


def stream_answer(prompt: str, sink: dict):
    """Generator of answer tokens; collects citations in `sink` for rendering afterwards."""
    try:
        with api("POST", "/api/v1/chat/stream", json={"query": prompt, "session_id": st.session_state.session_id},
                 stream=True, timeout=120) as response:
            if response.status_code != 200:
                yield f"⚠️ {error_text(response)}"
                return
            for event, data in sse_events(response):
                if event == "token":
                    yield data["text"]
                elif event == "citations":
                    sink["citations"] = data["citations"]
                elif event == "error":
                    yield f"\n\n⚠️ {data['detail']}"
    except requests.RequestException as exc:
        yield f"⚠️ Connection problem: {exc}"


def chat_tab() -> None:
    if "session_id" not in st.session_state:
        st.session_state.session_id = uuid.uuid4().hex
        st.session_state.messages = []
    if st.button("🆕 New conversation"):
        st.session_state.session_id = uuid.uuid4().hex
        st.session_state.messages = []
        st.rerun()
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            render_citations(message.get("citations", []))

    if prompt := st.chat_input("Ask about stock, expiry dates, storage rules, interactions..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            sink: dict = {"citations": []}
            answer = st.write_stream(stream_answer(prompt, sink))
            render_citations(sink["citations"])
        st.session_state.messages.append({"role": "assistant", "content": answer, "citations": sink["citations"]})


# ----------------------------------------------------------------------------- inventory
def inventory_tab() -> None:
    days = st.slider("Expiry look-ahead (days)", 7, 365, 60)
    response = api("GET", f"/api/v1/inventory/alerts?days={days}")
    if response.status_code != 200:
        st.error(error_text(response))
        return
    alerts = response.json()
    col1, col2, col3 = st.columns(3)
    col1.metric("Expired batches", len(alerts["expired"]))
    col2.metric(f"Expiring in {days} days", len(alerts["expiring_soon"]))
    col3.metric("Low-stock medicines", len(alerts["low_stock"]))
    for title, key in (("🔴 Expired", "expired"), ("🟠 Expiring soon", "expiring_soon"), ("🟡 Low stock", "low_stock")):
        if alerts[key]:
            st.subheader(title)
            st.dataframe(pd.DataFrame(alerts[key]), hide_index=True, width="stretch")
    st.subheader("All batches")
    batches = api("GET", "/api/v1/inventory/batches")
    if batches.status_code == 200:
        st.dataframe(pd.DataFrame(batches.json()), hide_index=True, width="stretch")
    with st.expander("Daily report (raw)"):
        st.json(api("GET", "/api/v1/inventory/report/daily").json())


# ----------------------------------------------------------------------------- documents
def documents_tab() -> None:
    response = api("GET", "/api/v1/documents")
    documents = response.json() if response.status_code == 200 else []
    st.caption("Uploaded documents are chunked and become searchable by the assistant immediately.")
    if documents:
        st.dataframe(pd.DataFrame(documents), hide_index=True, width="stretch")
    if can("admin"):
        upload = st.file_uploader("Upload a label / SOP (PDF, TXT, MD)", type=["pdf", "txt", "md"])
        if upload and st.button("Index document"):
            result = api("POST", "/api/v1/documents", files={"file": (upload.name, upload.getvalue())}, timeout=120)
            if result.status_code == 201:
                st.success(f"Indexed {result.json()['chunks']} chunks from {upload.name}.")
                st.rerun()
            else:
                st.error(error_text(result))
        if documents:
            target = st.selectbox("Delete a document", [""] + [f"{d['filename']} · {d['id']}" for d in documents])
            if target and st.button("Delete", type="secondary"):
                result = api("DELETE", f"/api/v1/documents/{target.split(' · ')[-1]}")
                st.success("Deleted.") if result.status_code == 204 else st.error(error_text(result))
                st.rerun()
    query = st.text_input("Test retrieval (what would the assistant find?)")
    if query:
        for hit in api("GET", "/api/v1/documents/search", params={"q": query}).json():
            page = f" · page {hit['page']}" if hit["page"] else ""
            st.markdown(f"**{hit['source']}**{page} · score {hit['score']}")
            st.caption(hit["snippet"])


# ----------------------------------------------------------------------------- stock movements
def movements_tab() -> None:
    batches = api("GET", "/api/v1/inventory/batches").json()
    labels = {f"{b['batch_id']} · {b['medicine']} · {b['quantity']} units": b["batch_id"] for b in batches}
    with st.form("movement"):
        batch = st.selectbox("Batch", list(labels))
        kind = st.radio("Movement", ["stock_in", "stock_out"], horizontal=True)
        quantity = st.number_input("Quantity", min_value=1, max_value=100000, value=1)
        note = st.text_input("Note (optional)")
        if st.form_submit_button("Review movement"):
            result = api("POST", "/api/v1/inventory/movements",
                         json={"batch_id": labels[batch], "movement_type": kind, "quantity": int(quantity), "note": note or None})
            if result.status_code == 201:
                st.session_state.pending = result.json()
            else:
                st.session_state.pop("pending", None)
                st.error(error_text(result))
    pending = st.session_state.get("pending")
    if pending:
        st.warning(f"**Please confirm:** {pending['summary']}")
        left, right = st.columns(2)
        if left.button("✅ Confirm"):
            result = api("POST", f"/api/v1/inventory/movements/{pending['confirmation_token']}/confirm")
            st.session_state.pop("pending", None)
            st.success(f"Done. New quantity: {result.json()['new_quantity']}") if result.status_code == 200 else st.error(error_text(result))
        if right.button("✖ Cancel"):
            st.session_state.pop("pending", None)
            st.rerun()


def audit_tab() -> None:
    response = api("GET", "/api/v1/admin/audit?limit=200")
    if response.status_code == 200:
        st.dataframe(pd.DataFrame(response.json()), hide_index=True, width="stretch")


# ----------------------------------------------------------------------------- main
if "token" not in st.session_state:
    login_screen()
    st.stop()

with st.sidebar:
    st.markdown(f"**{st.session_state.username}** · {st.session_state.role}")
    if st.button("Sign out"):
        logout()
    st.caption(f"API: {API_URL}")

tab_names = ["💬 Assistant", "📦 Inventory", "📄 Documents"]
if can("pharmacist"):
    tab_names.append("🔁 Stock movement")
if can("admin"):
    tab_names.append("🧾 Audit log")
tabs = st.tabs(tab_names)
tabs[0].empty()
with tabs[0]:
    chat_tab()
with tabs[1]:
    inventory_tab()
with tabs[2]:
    documents_tab()
if can("pharmacist"):
    with tabs[3]:
        movements_tab()
if can("admin"):
    with tabs[-1]:
        audit_tab()
