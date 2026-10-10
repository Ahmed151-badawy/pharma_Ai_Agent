# 💊 Pharma AI Agent

An AI assistant for pharmacy operations. Ask questions in plain language and it answers from **live inventory data**
(PostgreSQL) and **drug documentation** (PDF labels, SOPs, guidelines), and **shows exactly which SQL query or
document passage each answer came from**.

> **Demo data & disclaimer:** the bundled guidelines are sample text, not official FDA content. The assistant provides
> operational information only and is not a substitute for a pharmacist's or physician's judgment.

<!-- Live demo: https://your-demo-url.example (see docs/DEPLOYMENT.md) -->

## Features

| | |
|---|---|
| 🧠 **Agent** | LangGraph ReAct agent (Groq LLM) with three tools: read-only SQL, hybrid document search, inventory alerts |
| 💬 **Conversation memory** | Follow-ups work ("and its expiry date?"). Memory is per user and per session |
| ⚡ **Streaming** | Token-by-token answers over Server-Sent Events (`/api/v1/chat/stream`) |
| 📎 **Source citations** | Every answer returns the SQL it ran and the document chunks (file + page) it used |
| 📄 **Document ingestion** | Upload PDF/TXT/MD → chunked with metadata → searchable immediately (vector + BM25, fused with RRF) |
| 📦 **Inventory** | Expiry & low-stock alerts, daily report, **two-step confirmed** stock in/out with an inventory log |
| 🔐 **Security** | JWT auth, roles (viewer / pharmacist / admin), audit log, rate limiting, hardened SQL (sqlglot allow-list + read-only role) |
| 🔭 **Observability** | JSON logs with request ids, `/health` + `/ready`, optional LangSmith tracing |
| 🗄️ **Database** | SQLAlchemy models + Alembic migrations (also adopts a database from the first version of this project) |
| 🖥️ **Clients** | Streamlit web UI and a desktop (CustomTkinter) client |
| 🚀 **DevOps** | Docker (non-root, health check), docker-compose, CI (lint + tests on real PostgreSQL), CD to GitHub Container Registry |

## Architecture

```mermaid
flowchart LR
    UI[Streamlit web UI / Desktop GUI] -- HTTPS + JWT --> API[FastAPI]
    API --> AUTH[Auth, roles, rate limit, audit]
    API --> AGENT[LangGraph ReAct agent<br/>Groq LLM + memory]
    AGENT --> T1[SQL tool<br/>sqlglot guard + read-only role]
    AGENT --> T2[Guidelines search<br/>FAISS + BM25 + RRF]
    AGENT --> T3[Alerts tool]
    T1 --> PG[(PostgreSQL)]
    T3 --> PG
    AUTH --> PG
    T2 --> IDX[(FAISS index<br/>PDF chunks + metadata)]
    API -- upload --> IDX
```

## Quick start

```bash
cp .env.example .env        # set GROQ_API_KEY, JWT_SECRET, ADMIN_PASSWORD (no spaces around "=")
docker compose up --build   # Postgres + API + web UI; migrations and demo data are automatic
```

* Web UI: http://localhost:8501 · API docs: http://localhost:8000/docs
* Sign in with `ADMIN_USERNAME` / `ADMIN_PASSWORD` from your `.env`.

Try asking: *"What needs attention?"*, *"What is the stock of Amoxicillin batch AMX-2026?"* then *"and how should it be stored?"*

### Without Docker
```bash
pip install -r requirements.txt
alembic upgrade head && python -m scripts.seed_demo_data
uvicorn app.main:app --reload          # DB_HOST=localhost in .env
streamlit run web/app.py               # in a second terminal (pip install -r web/requirements.txt)
```

## API in 30 seconds

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"..."}' | jq -r .access_token)

# Ask a question (reuse "session_id" from the answer for follow-ups)
curl -s -X POST localhost:8000/api/v1/chat -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"query":"Which batches expire in the next 60 days?"}'

# Stream the answer (Server-Sent Events: session, tool_call, tool_result, token, citations, done)
curl -N -X POST localhost:8000/api/v1/chat/stream -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"query":"How should I store metformin?"}'
```

| Endpoint | Role | Purpose |
|---|---|---|
| `POST /api/v1/auth/login` | - | Get a JWT (rate limited) |
| `POST /api/v1/chat`, `/chat/stream` | viewer | Ask the agent (JSON or SSE) |
| `GET /api/v1/inventory/alerts?days=60` · `/report/daily` · `/batches` | viewer | Alerts, report, batch list |
| `POST /api/v1/inventory/movements` → `POST .../{token}/confirm` | pharmacist | Stock in/out in two confirmed steps |
| `GET/POST/DELETE /api/v1/documents`, `GET /documents/search` | viewer / admin | Manage and test the knowledge base |
| `POST /api/v1/auth/users`, `GET /api/v1/admin/audit` | admin | Users and audit trail |
| `GET /health`, `/ready` | - | Liveness / readiness probes |

## Security model

* **Roles** are read from the database on every request, so deactivating a user takes effect immediately.
* **The LLM never writes data.** Stock changes only happen through the two-step REST flow and are attributed to a user.
* **SQL written by the LLM** is parsed with sqlglot: one `SELECT` only, tables limited to `medicines`, `batches`,
  `inventory_logs`; unknown functions, comments, schema-qualified tables and data-modifying CTEs are rejected.
  It then runs in a read-only transaction with a 5 s timeout, optionally as a Postgres role with `SELECT` on those
  three tables only (`READONLY_DB_PASSWORD`), so it can never read `users` or `audit_logs`.
* **Conversation isolation:** the memory key includes the username, so session ids cannot be guessed across users.
* Secrets come from environment variables; nothing is hard-coded. Login failures are audited and rate limited.

## Testing

```bash
pip install -r requirements-dev.txt
createdb pharma_test            # or: export DATABASE_URL=postgresql://user:pass@host/pharma_test
pytest -v                       # 80+ tests: SQL guard, RAG, agent (scripted LLM), API, roles, migrations, DB role
ruff check .
python -m eval.run_retrieval_eval --k 1     # retrieval quality with the real embedding model
```
Tests run against a real PostgreSQL (the Alembic migrations build the schema), use fake embeddings and a scripted
chat model, so they need neither internet nor an API key.

## Configuration

See [`.env.example`](.env.example) for every variable. Highlights: `GROQ_API_KEY`, `JWT_SECRET`, `ADMIN_USERNAME/PASSWORD`,
`DB_*` or `DATABASE_URL`, `READONLY_DB_PASSWORD`, `CHAT_RATE_LIMIT_PER_MINUTE`, `RETRIEVAL_K`, `LANGSMITH_*`.

## Project layout

```
app/            FastAPI app: routers/, agent.py, rag.py, sql_guard.py, auth.py, inventory.py, models.py ...
alembic/        database migrations          scripts/   start.sh, seed, read-only role, index build
web/            Streamlit UI                 gui.py     desktop client
tests/          pytest suite                 eval/      retrieval evaluation set
deploy/ docs/   ECS task definition, Render blueprint, deployment guide
```

## Known limitations (and the fix)

* Conversation memory and the rate limiter are per process → Postgres checkpointer / Redis before scaling out.
* The FAISS index is a local file → use a persistent volume, or move to pgvector.
* Scanned PDFs have no text layer → add OCR.
* Access tokens only, no refresh / revocation list.

Details in [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).
