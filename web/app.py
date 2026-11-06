"""Streamlit web UI for the Pharma AI Agent.

Pages: Assistant (streaming chat + sources), Inventory, Documents, Stock movement, Audit log.
"""
import base64
import html
import json
import os
import uuid
from contextlib import contextmanager
from functools import lru_cache

import pandas as pd
import requests
import streamlit as st
from PIL import Image

API_URL = os.getenv("API_URL", "http://localhost:8000")
ROLE_RANK = {"viewer": 1, "pharmacist": 2, "admin": 3}
HERE = os.path.dirname(os.path.abspath(__file__))
LOGO = os.path.join(HERE, "assets", "logo.svg")
DOESY = os.path.join(HERE, "assets", "doesy")  # mascot assets, see docs/BRAND.md
ASSISTANT_AVATAR = os.path.join(DOESY, "doesy-badge-128.png")

st.set_page_config(page_title="Pharma AI Assistant", page_icon=Image.open(os.path.join(DOESY, "favicon-64.png")),
                   layout="wide")

# ----------------------------------------------------------------------------- styling
CSS = """
<style>
:root { --brand:#6E34D1; --brand-soft:#EDE5FF; --ink:#0F172A; --muted:#64748B; --line:#E2E8F0; }

.block-container { padding-top: 2rem; padding-bottom: 5rem; max-width: 1180px; }
footer { visibility: hidden; }
h1, h2, h3, h4, h5 { letter-spacing: -0.01em; }

/* page header */
.page-title { font-size: 1.75rem; font-weight: 700; color: var(--ink); line-height: 1.2; margin: 0; }
.page-sub   { color: var(--muted); margin: .25rem 0 1.25rem; font-size: .95rem; }

/* sidebar */
[data-testid="stSidebar"] { border-right: 1px solid var(--line); }
.usercard { display:flex; align-items:center; gap:.7rem; padding:.7rem .8rem; border:1px solid var(--line);
            border-radius:12px; background:#F8FAFC; margin-bottom:.6rem; }
.avatar   { width:36px; height:36px; border-radius:50%; background:var(--brand); color:#fff; display:flex;
            align-items:center; justify-content:center; font-weight:700; flex:none; }
.uname    { font-weight:600; color:var(--ink); line-height:1.1; margin-bottom:.2rem; }

/* pills */
.pill { display:inline-block; padding:.12rem .55rem; border-radius:999px; font-size:.72rem; font-weight:600;
        letter-spacing:.02em; text-transform:uppercase; }
.pill-viewer     { background:#E2E8F0; color:#334155; }
.pill-pharmacist { background:#EDE5FF; color:#4C1D95; }
.pill-admin      { background:#CFFAFE; color:#155E75; }
.pill-ok   { background:#DCFCE7; color:#166534; text-transform:none; }
.pill-bad  { background:#FEE2E2; color:#991B1B; text-transform:none; }

/* KPI cards */
.kpi { background:#fff; border:1px solid var(--line); border-radius:14px; padding:1rem 1.1rem;
       box-shadow:0 1px 2px rgba(15,23,42,.04); border-left-width:5px; }
.kpi-label { color:var(--muted); font-size:.8rem; font-weight:600; text-transform:uppercase; letter-spacing:.04em; }
.kpi-value { font-size:2rem; font-weight:700; color:var(--ink); line-height:1.15; margin-top:.15rem; }
.kpi-hint  { color:var(--muted); font-size:.8rem; margin-top:.1rem; }
.kpi-neutral { border-left-color:#94A3B8; } .kpi-good { border-left-color:#16A34A; }
.kpi-red { border-left-color:#DC2626; } .kpi-amber { border-left-color:#F59E0B; } .kpi-yellow { border-left-color:#EAB308; }

/* chat */
[data-testid="stChatMessage"] { border-radius:14px; padding:.9rem 1rem; }
.hero { text-align:center; padding:1.2rem 1rem 1.4rem; }
.hero h2 { margin:0 0 .35rem; font-size:1.6rem; }
.hero p  { color:var(--muted); margin:0; }

/* Doesy, the mascot */
.hero-img { display:block; margin:0 auto .7rem; height:168px; width:auto; transform-origin:50% 92%;
            animation:doesy-float 3.4s ease-in-out infinite; }
@keyframes doesy-float { 0%,100% { transform:translateY(0) rotate(-1.5deg); } 50% { transform:translateY(-7px) rotate(2deg); } }
.page-head { display:flex; align-items:center; gap:.8rem; margin-bottom:1.1rem; }
.page-head img { width:46px; height:46px; flex:none; }
.page-head .page-sub { margin:.1rem 0 0; }
.dnote { display:flex; align-items:center; gap:.9rem; padding:.8rem 1rem; border-radius:14px; border:1px solid var(--line);
         background:#fff; }
.dnote img { width:52px; height:52px; flex:none; }
.dnote-good { background:#F3FBF5; border-color:#BBF7D0; color:#166534; }
.dnote-good img { animation:doesy-pop .7s ease-out 1; }
.dnote-empty { flex-direction:column; text-align:center; color:var(--muted); padding:1.1rem; }
.dnote-empty img { animation:doesy-tilt 4s ease-in-out infinite; }
@keyframes doesy-pop { 0% { transform:scale(.6) rotate(-8deg); } 60% { transform:scale(1.12) rotate(4deg); } 100% { transform:scale(1); } }
@keyframes doesy-tilt { 0%,100% { transform:rotate(-4deg); } 50% { transform:rotate(4deg); } }
.doesy-sleepy { filter:grayscale(.85) opacity(.65); }
.side-status { display:flex; align-items:center; gap:.5rem; }
.side-status img { width:26px; height:26px; }

/* loading: Doesy pushes a pill along */
.push { display:flex; align-items:center; gap:.9rem; padding:.3rem 0; }
.push-stage { position:relative; width:168px; height:58px; flex:none; overflow:hidden; }
.push-bot { position:absolute; left:2px; bottom:0; height:54px; width:auto; transform-origin:50% 100%;
            animation:push-bot 1.9s ease-in-out infinite; }
.push-pill { position:absolute; left:54px; bottom:7px; width:26px; height:12px; border-radius:999px; box-sizing:border-box;
             border:2px solid #6E34D1; background:linear-gradient(90deg,#6E34D1 50%,#fff 50%);
             animation:push-pill 1.9s ease-in-out infinite; }
@keyframes push-bot { 0% { transform:translateX(0) rotate(0); } 14% { transform:translateX(-3px) rotate(-5deg); }
                      52% { transform:translateX(52px) rotate(8deg); } 100% { transform:translateX(0) rotate(0); } }
@keyframes push-pill { 0% { transform:translateX(0) rotate(0); opacity:0; } 14% { transform:translateX(0) rotate(0); opacity:1; }
                       52% { transform:translateX(52px) rotate(500deg); opacity:1; }
                       80% { transform:translateX(88px) rotate(700deg); opacity:1; }
                       92% { transform:translateX(100px) rotate(760deg); opacity:0; } 100% { opacity:0; } }
.push-label { color:var(--muted); font-size:.92rem; }
.push-label::after { content:""; animation:push-dots 1.4s steps(1,end) infinite; }
@keyframes push-dots { 0% { content:""; } 25% { content:"."; } 50% { content:".."; } 75% { content:"..."; } }
@media (prefers-reduced-motion: reduce) {
  .hero-img, .push-bot, .dnote img, .push-label::after { animation:none !important; }
  .push-pill { animation:none !important; opacity:1; }
}

/* generic polish */
.stButton > button, .stDownloadButton > button { border-radius:10px; font-weight:500; }
[data-testid="stVerticalBlockBorderWrapper"] { border-radius:14px; }
[data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:12px; overflow:hidden; }
.section-title { font-weight:600; font-size:1.05rem; margin:1.1rem 0 .4rem; color:var(--ink); }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ----------------------------------------------------------------------------- Doesy (mascot) helpers
@lru_cache(maxsize=None)
def doesy_uri(name: str) -> str:
    with open(os.path.join(DOESY, name), "rb") as fh:
        return "data:image/png;base64," + base64.b64encode(fh.read()).decode()


def doesy_img(name: str, cls: str = "", height: int | None = None) -> str:
    style = f" style='height:{height}px'" if height else ""
    return f"<img class='{cls}' src='{doesy_uri(name)}' alt='Doesy'{style}>"


def push_loader(text: str) -> str:
    """Doesy pushing a pill along while we wait (pure CSS; see .push in the stylesheet)."""
    return (f"<div class='push'><div class='push-stage'><span class='push-pill'></span>"
            f"{doesy_img('doesy-full-128.png', 'push-bot')}</div>"
            f"<span class='push-label'>{html.escape(text)}</span></div>")


@contextmanager
def working(text: str):
    """Show the pill-pushing loader for the duration of a block."""
    slot = st.empty()
    slot.markdown(push_loader(text), unsafe_allow_html=True)
    try:
        yield
    finally:
        slot.empty()


def doesy_note(text: str, tone: str = "good") -> None:
    st.markdown(f"<div class='dnote dnote-{tone}'>{doesy_img('doesy-badge-128.png')}<div>{html.escape(text)}</div></div>",
                unsafe_allow_html=True)


# ----------------------------------------------------------------------------- API helpers
def api(method: str, path: str, **kwargs) -> requests.Response:
    headers = {"Authorization": f"Bearer {st.session_state.token}"} if st.session_state.get("token") else {}
    response = requests.request(method, f"{API_URL}{path}", headers=headers, timeout=kwargs.pop("timeout", 30), **kwargs)
    if response.status_code == 401 and st.session_state.get("token"):  # token expired
        logout()
    return response


def logout() -> None:
    for key in ("token", "role", "username", "messages", "session_id", "pending", "queued_prompt", "flash"):
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


def fetch(path: str, default=None, **params):
    """GET helper: returns parsed JSON, or `default` after showing a friendly error."""
    try:
        response = api("GET", path, params=params or None)
    except requests.RequestException as exc:
        st.error(f"Cannot reach the API: {exc}")
        return default
    if response.status_code != 200:
        st.error(error_text(response))
        return default
    return response.json()


@st.cache_data(ttl=10, show_spinner=False)
def api_online(url: str) -> bool:
    try:
        return requests.get(f"{url}/health", timeout=3).status_code == 200
    except requests.RequestException:
        return False


# ----------------------------------------------------------------------------- UI helpers
def page_header(title: str, subtitle: str) -> None:
    st.markdown(f"<div class='page-head'>{doesy_img('doesy-badge-128.png')}<div>"
                f"<div class='page-title'>{html.escape(title)}</div><div class='page-sub'>{html.escape(subtitle)}</div>"
                f"</div></div>", unsafe_allow_html=True)


def kpi(label: str, value, tone: str = "neutral", hint: str = "") -> str:
    hint_html = f"<div class='kpi-hint'>{html.escape(hint)}</div>" if hint else ""
    return (f"<div class='kpi kpi-{tone}'><div class='kpi-label'>{html.escape(label)}</div>"
            f"<div class='kpi-value'>{value}</div>{hint_html}</div>")


LABELS = {
    "batch_id": "Batch", "medicine": "Medicine", "quantity": "Units", "expiration_date": "Expires",
    "days_left": "Days left", "status": "Status", "supplier": "Supplier", "usable_stock": "Usable stock",
    "minimum_stock_level": "Minimum level", "coverage": "Coverage", "filename": "File", "pages": "Pages",
    "chunks": "Chunks", "uploaded_by": "Uploaded by", "created_at": "Uploaded", "id": "ID", "ts": "Time",
    "user": "User", "action": "Action", "detail": "Detail", "request_id": "Request", "ip": "IP",
    "type": "Type", "transactions": "Transactions", "net_units": "Net units",
}


def _days_style(value) -> str:
    if pd.isna(value):
        return ""
    if value < 0:
        return "background-color:#FEE2E2;color:#991B1B;font-weight:600"
    if value <= 30:
        return "background-color:#FEF3C7;color:#92400E;font-weight:600"
    return "background-color:#DCFCE7;color:#166534"


def show_table(rows: list[dict], height: int | None = None) -> None:
    """Render records as a tidy table: friendly headers, real dates, colour-coded expiry."""
    df = pd.DataFrame(rows)
    if df.empty:
        return
    for col in ("expiration_date",):
        if col in df:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    for col in ("created_at", "ts"):
        if col in df:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    if {"usable_stock", "minimum_stock_level"} <= set(df.columns):
        minimum = df["minimum_stock_level"].replace(0, pd.NA)
        df["coverage"] = (df["usable_stock"] / minimum).astype("float").clip(upper=1).fillna(1)
    config = {}
    for col in df.columns:
        label = LABELS.get(col, col.replace("_", " ").title())
        if col == "expiration_date":
            config[col] = st.column_config.DateColumn(label, format="DD MMM YYYY")
        elif col in ("created_at", "ts"):
            config[col] = st.column_config.DatetimeColumn(label, format="DD MMM YYYY, HH:mm")
        elif col == "coverage":
            config[col] = st.column_config.ProgressColumn(label, min_value=0, max_value=1, format="percent")
        elif col in ("days_left", "quantity", "usable_stock", "minimum_stock_level", "net_units", "transactions"):
            config[col] = st.column_config.NumberColumn(label, format="%d")
        else:
            config[col] = st.column_config.Column(label)
    data = df.style.map(_days_style, subset=["days_left"]) if "days_left" in df else df
    extra = {"height": height} if height else {}
    st.dataframe(data, hide_index=True, width="stretch", column_config=config, **extra)


def empty_state(text: str) -> None:
    st.markdown(f"<div class='dnote dnote-empty'>{doesy_img('doesy-badge-128.png')}<div>{html.escape(text)}</div></div>",
                unsafe_allow_html=True)


# ----------------------------------------------------------------------------- login
def login_screen() -> None:
    _, middle, _ = st.columns([1, 1.15, 1])
    with middle:
        st.write("")
        st.write("")
        with st.container(border=True):
            st.markdown(
                "<div style='text-align:center;padding:.5rem 0 .25rem'>"
                f"{doesy_img('doesy-full-256.png', 'hero-img', 132)}"
                "<div class='page-title'>Pharma AI Assistant</div>"
                "<div class='page-sub' style='margin-bottom:.5rem'>Hi, I'm Doesy. Sign in and I'll help with inventory &amp; compliance.</div>"
                "</div>", unsafe_allow_html=True)
            with st.form("login", border=False):
                username = st.text_input("Username", placeholder="your.username")
                password = st.text_input("Password", type="password", placeholder="••••••••")
                submitted = st.form_submit_button("Sign in", type="primary", width="stretch")
            if submitted:
                try:
                    with working("Signing you in"):
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
        st.caption("Answers are grounded in your inventory database and uploaded labels, and always show their sources.")


# ----------------------------------------------------------------------------- chat
SUGGESTIONS = [
    ("inventory_2", "Check stock", "What is the current stock level of Amoxicillin?"),
    ("notification_important", "What needs attention?", "What is expired, expiring soon, or low on stock?"),
    ("menu_book", "Storage & safety", "What are the storage requirements and contraindications for Ibuprofen?"),
]


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
    docs = sum(c["type"] == "document" for c in citations)
    queries = sum(c["type"] == "sql" for c in citations)
    summary = ", ".join(part for part in (f"{docs} document{'s' if docs != 1 else ''}" if docs else "",
                                          f"{queries} database quer{'ies' if queries != 1 else 'y'}" if queries else "") if part)
    with st.expander(f"Sources · {summary or len(citations)}", icon=":material/fact_check:"):
        for c in citations:
            with st.container(border=True):
                if c["type"] == "sql":
                    st.caption(f":material/database: Database query · {c['row_count']} row(s)")
                    st.code(c["query"], language="sql")
                elif c["type"] == "document":
                    page = f" · page {c['page']}" if c.get("page") else ""
                    st.caption(f":material/description: {c['source']}{page}")
                    st.markdown(f"> {c['snippet']}")
                elif c["type"] == "inventory_alerts":
                    st.caption(f":material/notification_important: Inventory alerts · next {c['days_ahead']} days · {c['counts']}")


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


def chat_page() -> None:
    if "session_id" not in st.session_state:
        st.session_state.session_id = uuid.uuid4().hex
        st.session_state.messages = []
    messages = st.session_state.messages

    head, action = st.columns([5, 1], vertical_alignment="center")
    with head:
        page_header("Assistant", "Ask Doesy about stock, expiry dates, storage rules and drug interactions.")
    with action:
        if st.button("New chat", icon=":material/add:", width="stretch", disabled=not messages):
            st.session_state.session_id = uuid.uuid4().hex
            st.session_state.messages = []
            st.rerun()

    # Read the input first so a submitted prompt never leaves the empty-state cards on screen.
    typed = st.chat_input("Ask about stock, expiry dates, storage rules, interactions...")
    prompt = st.session_state.pop("queued_prompt", None) or typed
    if prompt:
        messages.append({"role": "user", "content": prompt})

    if not messages:
        st.markdown(f"<div class='hero'>{doesy_img('doesy-full-256.png', 'hero-img')}<h2>Hi, I'm Doesy. How can I help today?</h2>"
                    "<p>Ask in plain language — every answer cites the database rows or label pages it came from.</p></div>",
                    unsafe_allow_html=True)
        for col, (icon, title, question) in zip(st.columns(len(SUGGESTIONS)), SUGGESTIONS):
            with col, st.container(border=True):
                st.markdown(f"**:material/{icon}: {title}**")
                st.caption(question)
                if st.button("Ask this", key=f"suggest_{icon}", width="stretch"):
                    st.session_state.queued_prompt = question
                    st.rerun()

    for message in messages:
        avatar = ":material/person:" if message["role"] == "user" else ASSISTANT_AVATAR
        with st.chat_message(message["role"], avatar=avatar):
            st.markdown(message["content"])
            render_citations(message.get("citations", []))

    if prompt:
        with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
            sink: dict = {"citations": []}
            thinking = st.empty()
            thinking.markdown(push_loader("Searching inventory and documents"), unsafe_allow_html=True)

            def tokens():
                first = True
                for token in stream_answer(prompt, sink):
                    if first:
                        thinking.empty()
                        first = False
                    yield token

            answer = st.write_stream(tokens())
            thinking.empty()
            render_citations(sink["citations"])
        messages.append({"role": "assistant", "content": answer, "citations": sink["citations"]})


# ----------------------------------------------------------------------------- inventory
def inventory_page() -> None:
    page_header("Inventory", "Live stock levels, expiry risk and low-stock alerts.")
    slider_col, refresh_col = st.columns([4, 1], vertical_alignment="bottom")
    days = slider_col.slider("Expiry look-ahead (days)", 7, 365, 60)
    if refresh_col.button("Refresh", icon=":material/refresh:", width="stretch"):
        st.rerun()

    with working("Checking the shelves"):
        alerts = fetch("/api/v1/inventory/alerts", days=days)
        report = fetch("/api/v1/inventory/report/daily") if alerts is not None else None
    if alerts is None:
        return
    report = report or {}
    totals = report.get("totals", {})

    cards = st.columns(4)
    cards[0].markdown(kpi("Units in stock", f"{totals.get('units_in_stock', '–'):,}" if totals else "–", "neutral",
                          f"{totals.get('medicines', '–')} medicines · {totals.get('batches', '–')} batches"),
                      unsafe_allow_html=True)
    cards[1].markdown(kpi("Expired batches", len(alerts["expired"]), "red" if alerts["expired"] else "good",
                          "Remove from dispensing" if alerts["expired"] else "None"), unsafe_allow_html=True)
    cards[2].markdown(kpi(f"Expiring in {days} d", len(alerts["expiring_soon"]),
                          "amber" if alerts["expiring_soon"] else "good", "Dispense first (FEFO)"
                          if alerts["expiring_soon"] else "None"), unsafe_allow_html=True)
    cards[3].markdown(kpi("Low-stock medicines", len(alerts["low_stock"]), "yellow" if alerts["low_stock"] else "good",
                          "Below minimum level" if alerts["low_stock"] else "None"), unsafe_allow_html=True)
    st.write("")

    attention = len(alerts["expired"]) + len(alerts["expiring_soon"]) + len(alerts["low_stock"])
    tab_attention, tab_batches, tab_report = st.tabs([f"Needs attention ({attention})", "All batches", "Daily report"])

    with tab_attention:
        if not attention:
            doesy_note("All clear — nothing is expired, expiring soon, or low on stock.", "good")
        for title, key in (("🔴 Expired", "expired"), ("🟠 Expiring soon", "expiring_soon"), ("🟡 Low stock", "low_stock")):
            if alerts[key]:
                st.markdown(f"<div class='section-title'>{title} · {len(alerts[key])}</div>", unsafe_allow_html=True)
                show_table(alerts[key])

    with tab_batches:
        batches = fetch("/api/v1/inventory/batches", default=[])
        if batches:
            df = pd.DataFrame(batches)
            search_col, status_col = st.columns([3, 2])
            needle = search_col.text_input("Search", placeholder="Medicine, batch or supplier",
                                           label_visibility="collapsed")
            statuses = sorted(df["status"].dropna().unique()) if "status" in df else []
            chosen = status_col.multiselect("Status", statuses, placeholder="Filter by status",
                                            label_visibility="collapsed") if statuses else []
            if needle:
                mask = df.astype(str).apply(lambda col: col.str.contains(needle, case=False, regex=False)).any(axis=1)
                df = df[mask]
            if chosen:
                df = df[df["status"].isin(chosen)]
            st.caption(f"{len(df)} of {len(batches)} batches")
            show_table(df.to_dict("records"), height=460)
        else:
            empty_state("No batches found.")

    with tab_report:
        if report:
            st.caption(f"Report date: {report.get('date', '–')}")
            st.markdown("<div class='section-title'>Movements today</div>", unsafe_allow_html=True)
            if report.get("movements_today"):
                show_table(report["movements_today"])
            else:
                empty_state("No stock movements recorded today.")
            with st.expander("Raw report (JSON)"):
                st.json(report)


# ----------------------------------------------------------------------------- documents
def documents_page() -> None:
    page_header("Documents", "Labels and SOPs are chunked and become searchable by the assistant immediately.")
    documents = fetch("/api/v1/documents", default=[])
    tabs = ["Library", "Test retrieval"] + (["Manage"] if can("admin") else [])
    tab_objs = st.tabs(tabs)

    with tab_objs[0]:
        if documents:
            cols = st.columns(3)
            cols[0].markdown(kpi("Documents", len(documents), "neutral"), unsafe_allow_html=True)
            cols[1].markdown(kpi("Pages", sum(d.get("pages", 0) for d in documents), "neutral"), unsafe_allow_html=True)
            cols[2].markdown(kpi("Searchable chunks", sum(d.get("chunks", 0) for d in documents), "good"),
                             unsafe_allow_html=True)
            st.write("")
            show_table([{k: v for k, v in d.items() if k != "id"} for d in documents])
        else:
            empty_state("No documents indexed yet." + (" Use the Manage tab to upload one." if can("admin") else ""))

    with tab_objs[1]:
        st.caption("Preview exactly which passages the assistant would retrieve for a question.")
        query = st.text_input("Question", placeholder="e.g. storage temperature for amoxicillin",
                              label_visibility="collapsed")
        if query:
            try:
                with working("Searching passages"):
                    result = api("GET", "/api/v1/documents/search", params={"q": query})
            except requests.RequestException as exc:
                st.error(f"Cannot reach the API: {exc}")
            else:
                hits = result.json() if result.status_code == 200 else []
                if result.status_code != 200:
                    st.error(error_text(result))
                elif not hits:
                    empty_state("No matching passages found.")
                for hit in hits:
                    with st.container(border=True):
                        page = f" · page {hit['page']}" if hit.get("page") else ""
                        st.markdown(f"**:material/description: {hit['source']}**{page}")
                        st.caption(f"Relevance score {hit['score']}")
                        st.markdown(f"> {hit['snippet']}")

    if can("admin"):
        with tab_objs[2]:
            with st.container(border=True):
                st.markdown("**Upload a label or SOP**")
                upload = st.file_uploader("PDF, TXT or MD", type=["pdf", "txt", "md"], label_visibility="collapsed")
                if st.button("Index document", icon=":material/upload:", type="primary", disabled=not upload):
                    with working("Indexing document"):
                        result = api("POST", "/api/v1/documents", files={"file": (upload.name, upload.getvalue())},
                                     timeout=120)
                    if result.status_code == 201:
                        st.session_state.flash = f"Indexed {result.json()['chunks']} chunks from {upload.name}."
                        st.rerun()
                    else:
                        st.error(error_text(result))
            if documents:
                with st.container(border=True):
                    st.markdown("**Delete a document**")
                    target = st.selectbox("Document", [f"{d['filename']} · {d['id']}" for d in documents],
                                          index=None, placeholder="Choose a document", label_visibility="collapsed")
                    sure = st.checkbox("Remove it from the assistant's knowledge permanently", disabled=not target)
                    if st.button("Delete", icon=":material/delete:", disabled=not (target and sure)):
                        result = api("DELETE", f"/api/v1/documents/{target.split(' · ')[-1]}")
                        if result.status_code == 204:
                            st.session_state.flash = "Document deleted."
                            st.rerun()
                        else:
                            st.error(error_text(result))
    if st.session_state.get("flash"):
        st.toast(st.session_state.pop("flash"), icon=":material/check_circle:")


# ----------------------------------------------------------------------------- stock movements
MOVEMENT_LABELS = {"stock_in": "Stock in · receive", "stock_out": "Stock out · dispense", "disposal": "Disposal · write-off"}


def movements_page() -> None:
    page_header("Stock movement", "Two steps: review the change, then confirm. Nothing is applied until you confirm.")
    batches = fetch("/api/v1/inventory/batches", default=[])
    if not batches:
        empty_state("No batches available.")
        return
    by_label = {f"{b['batch_id']} · {b['medicine']} · {b['quantity']} units": b for b in batches}

    if st.session_state.get("flash"):
        st.success(st.session_state.pop("flash"), icon=":material/check_circle:")

    left, right = st.columns([3, 2], gap="large")
    with left, st.container(border=True):
        st.markdown("**1 · Enter details**")
        label = st.selectbox("Batch", list(by_label))
        batch = by_label[label]
        days_left = batch.get("days_left")
        pill = ("pill-bad", "Expired") if days_left is not None and days_left < 0 else ("pill-ok", f"{days_left} days left")
        st.markdown(f"<span class='pill {pill[0]}'>{pill[1]}</span> &nbsp;<span style='color:#64748B;font-size:.85rem'>"
                    f"Expires {html.escape(str(batch.get('expiration_date', '–')))} · "
                    f"{html.escape(str(batch.get('supplier') or 'no supplier'))}</span>", unsafe_allow_html=True)
        kind = st.radio("Movement", list(MOVEMENT_LABELS), format_func=MOVEMENT_LABELS.get, horizontal=True)
        quantity = st.number_input("Quantity", min_value=1, max_value=100000, value=1)
        note = st.text_input("Note (optional)", max_chars=200)
        if st.button("Review movement", type="primary", icon=":material/arrow_forward:", width="stretch"):
            result = api("POST", "/api/v1/inventory/movements",
                         json={"batch_id": batch["batch_id"], "movement_type": kind, "quantity": int(quantity),
                               "note": note or None})
            if result.status_code == 201:
                st.session_state.pending = result.json()
            else:
                st.session_state.pop("pending", None)
                st.error(error_text(result))

    with right, st.container(border=True):
        st.markdown("**2 · Review & confirm**")
        pending = st.session_state.get("pending")
        if not pending:
            st.caption("Submit the form to preview the change here.")
        else:
            st.warning(pending["summary"], icon=":material/rule:")
            if pending.get("expires_at"):
                st.caption(f"Confirmation expires {pending['expires_at']}")
            confirm, cancel = st.columns(2)
            if confirm.button("Confirm", icon=":material/check:", type="primary", width="stretch"):
                result = api("POST", f"/api/v1/inventory/movements/{pending['confirmation_token']}/confirm")
                st.session_state.pop("pending", None)
                if result.status_code == 200:
                    st.session_state.flash = f"Done. New quantity: {result.json()['new_quantity']}"
                    st.rerun()
                else:
                    st.error(error_text(result))
            if cancel.button("Cancel", icon=":material/close:", width="stretch"):
                st.session_state.pop("pending", None)
                st.rerun()


# ----------------------------------------------------------------------------- audit
def audit_page() -> None:
    page_header("Audit log", "Who did what, and when. Most recent entries first.")
    limit_col, action_col, search_col = st.columns([1, 1, 2], vertical_alignment="bottom")
    limit = limit_col.selectbox("Entries", [50, 100, 200, 500], index=2)
    entries = fetch("/api/v1/admin/audit", default=None, limit=limit)
    if entries is None:
        return
    if not entries:
        empty_state("No audit entries yet.")
        return
    df = pd.DataFrame(entries)
    df["detail"] = df["detail"].map(lambda d: d if isinstance(d, str) else json.dumps(d, default=str))
    chosen = action_col.selectbox("Action", ["All actions"] + sorted(df["action"].dropna().unique()))
    needle = search_col.text_input("Search", placeholder="Search user, detail, IP…", label_visibility="collapsed")
    if chosen != "All actions":
        df = df[df["action"] == chosen]
    if needle:
        df = df[df.astype(str).apply(lambda col: col.str.contains(needle, case=False, regex=False)).any(axis=1)]
    st.caption(f"{len(df)} of {len(entries)} entries")
    show_table(df.to_dict("records"), height=520)
    st.download_button("Download CSV", df.to_csv(index=False), "audit_log.csv", "text/csv", icon=":material/download:")


# ----------------------------------------------------------------------------- main
if "token" not in st.session_state:
    login_screen()
    st.stop()

if os.path.exists(LOGO):
    st.logo(LOGO, icon_image=os.path.join(DOESY, "doesy-badge-128.png"), size="large")

pages = {
    "Workspace": [
        st.Page(chat_page, title="Assistant", icon=":material/chat:", url_path="assistant", default=True),
        st.Page(inventory_page, title="Inventory", icon=":material/inventory_2:", url_path="inventory"),
        st.Page(documents_page, title="Documents", icon=":material/description:", url_path="documents"),
    ]
}
if can("pharmacist"):
    pages["Operations"] = [st.Page(movements_page, title="Stock movement", icon=":material/sync_alt:", url_path="movements")]
if can("admin"):
    pages["Administration"] = [st.Page(audit_page, title="Audit log", icon=":material/receipt_long:", url_path="audit")]
navigation = st.navigation(pages)

with st.sidebar:
    name = st.session_state.username or "user"
    role = st.session_state.role
    st.markdown(f"<div class='usercard'><div class='avatar'>{html.escape(name[:1].upper())}</div><div>"
                f"<div class='uname'>{html.escape(name)}</div><span class='pill pill-{role}'>{html.escape(role)}</span>"
                f"</div></div>", unsafe_allow_html=True)
    if st.button("Sign out", icon=":material/logout:", width="stretch"):
        logout()
    online = api_online(API_URL)
    st.markdown(f"<div class='side-status'>{doesy_img('doesy-badge-64.png', '' if online else 'doesy-sleepy')}"
                f"<span class='pill {'pill-ok' if online else 'pill-bad'}'>● API {'online' if online else 'offline'}</span></div>",
                unsafe_allow_html=True)
    st.caption(API_URL)

navigation.run()
