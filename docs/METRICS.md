# System Benchmark Metrics & Verification Baseline

**Project:** Pharma AI Agent  
**Date Evaluated:** 2026-10-20  
**Branch:** `feature/k8s-observability-dify`  
**Hardware Baseline:** Intel64 (4 CPU cores), 7.89 GB RAM, Windows 10 (10.0.19045-SP0)  
**LLM & Embedding Models:**
- LLM Provider / Model: Groq / `openai/gpt-oss-120b` (Developer / Free Tier On-Demand)
- Embedding Model: HuggingFace `sentence-transformers/all-MiniLM-L6-v2` (384-dimensional dense vectors)
- Keyword Search: BM25Okapi (`rank-bm25`)
- Fusion Algorithm: Reciprocal Rank Fusion (RRF, $k=60$)

---

## 1. Test Suite & Code Coverage Baseline

- **Total Test Cases:** 90 collected and executed
- **Pass / Fail:** **90 passed**, 0 failed (100% test pass rate in 85.01s)
- **Overall Code Coverage:** **94%** (1,031 statements, 66 missed)
- **Artifact:** [`docs/evidence/coverage_term.txt`](evidence/coverage_term.txt)

### Coverage Breakdown by Module

| Module | Statements | Missing Lines | Coverage % | Critical Functionality Verified |
|:---|:---:|:---:|:---:|:---|
| `app/__init__.py` | 1 | 0 | 100% | Package init |
| `app/agent.py` | 137 | 17 | 88% | LangGraph ReAct agent, state, tool dispatch, streaming |
| `app/audit.py` | 7 | 0 | 100% | Audit trail log writer |
| `app/auth.py` | 61 | 5 | 92% | Password hashing, JWT creation/validation, role guards |
| `app/config.py` | 58 | 1 | 98% | Pydantic BaseSettings, JWT fallback aliases, env parsing |
| `app/db.py` | 20 | 0 | 100% | SQLAlchemy engine & connection pool |
| `app/inventory.py` | 104 | 6 | 94% | Expiration reject, disposal, FEFO check, row locks |
| `app/logging_conf.py` | 27 | 8 | 70% | Structured JSON logger & contextvars |
| `app/main.py` | 75 | 8 | 89% | FastAPI app, middleware, exception handlers, probes |
| `app/models.py` | 69 | 0 | 100% | 7 SQLAlchemy declarative ORM models |
| `app/rag.py` | 178 | 14 | 92% | Vector search, BM25, RRF fusion, PDF/TXT chunking |
| `app/ratelimit.py` | 36 | 0 | 100% | Rate limiter deque |
| `app/routers/admin.py` | 13 | 0 | 100% | `/api/v1/admin/audit` endpoint |
| `app/routers/auth.py` | 34 | 1 | 97% | `/api/v1/auth/login`, `/me`, `/users` |
| `app/routers/chat.py` | 42 | 3 | 93% | `/api/v1/chat`, `/api/v1/chat/stream` |
| `app/routers/documents.py` | 36 | 0 | 100% | `/api/v1/documents`, upload, search, delete |
| `app/routers/inventory.py` | 30 | 0 | 100% | `/batches`, `/alerts`, `/fefo/recommend`, `/movements` |
| `app/schemas.py` | 65 | 1 | 98% | Pydantic request/response validation schemas |
| `app/sql_guard.py` | 38 | 2 | 95% | SQL AST parser, read-only transaction guard |
| **TOTAL** | **1,031** | **66** | **94%** | Full backend test coverage |

---

## 2. Retrieval Quality Benchmark (Vector vs. BM25 vs. Hybrid RRF)

- **Benchmark Dataset:** 66 questions evaluated across 11 authentic FDA / DailyMed drug monographs:
  - Antibiotics: *Amoxicillin*, *Azithromycin*
  - Analgesic / NSAID: *Ibuprofen*
  - Antidiabetic: *Metformin*
  - Proton Pump Inhibitor: *Omeprazole*
  - Antihypertensives / ACE / ARB: *Lisinopril*, *Losartan*, *Amlodipine*
  - Lipid-lowering / Statin: *Atorvastatin*
  - Thyroid Hormone: *Levothyroxine*
  - Respiratory / Bronchodilator: *Albuterol*
- **Query Types:** 50% exact-wording clinical queries + 50% paraphrased/colloquial inquiries.
- **Artifacts:** [`docs/evidence/retrieval_eval_table.md`](evidence/retrieval_eval_table.md), [`docs/evidence/retrieval_eval_raw.json`](evidence/retrieval_eval_raw.json)

### Comparative Retrieval Results

| Metric | Vector Only (FAISS `all-MiniLM-L6-v2`) | BM25 Only (Okapi) | Hybrid (RRF $k=60$) | Winner |
|:---|:---:|:---:|:---:|:---:|
| **Hit@1** | 84.9% | 69.7% | **84.9%** | Tie (Hybrid = Vector) |
| **Hit@3** | 95.5% | 89.4% | **98.5%** | **Hybrid (+3.0% over Vector)** |
| **Hit@5** | 98.5% | 98.5% | **100.0%** | **Hybrid (100% Recall in Top-5)** |
| **MRR**   | 0.9051 | 0.8091 | **0.9129** | **Hybrid (+0.0078 over Vector)** |

### Findings & Analysis
1. **Hybrid Outperformed Both Single Retrievers:** Hybrid RRF achieved the highest overall Mean Reciprocal Rank (**0.9129**) and reached **100.0% Hit@5**, ensuring no relevant guideline chunk was dropped outside the agent's context window.
2. **Complementary Strengths:**
   - BM25 excelled at exact numerical thresholds and acronyms (e.g., "eGFR below 30", "CABG", "CYP2C19").
   - Dense vector embeddings excelled at semantic paraphrasing (e.g. "quick diet pill" $\rightarrow$ "obesity or weight loss", "swollen ankles" $\rightarrow$ "peripheral edema").
   - RRF fusion successfully elevated relevant documents when either dense or sparse retrieval faltered.

---

## 3. Latency & Concurrency Benchmark

- **Target:** Live FastAPI backend running on local test database with REAL embedding model and live Groq LLM.
- **Rate Limit Errors:** **0 unhandled 429 errors** observed by caller (Groq client transparently retried transient 429 rate limit backoffs).
- **Artifacts:** [`docs/evidence/latency_results.txt`](evidence/latency_results.txt), [`docs/evidence/latency_results.json`](evidence/latency_results.json)

### Response Time & Throughput

| Scenario | Endpoint | Requests | Concurrency | p50 (Median) | p95 | 429 Rate Limits |
|:---|:---|:---:|:---:|:---:|:---:|:---:|
| **1. Retrieval Only** | `GET /api/v1/documents/search` | 20 | 3 | **151.11 ms** | **242.37 ms** | 0 |
| **2. SQL Tool E2E** | `POST /api/v1/chat` (stock query) | 10 | 2 | **2,826.12 ms** | **5,080.43 ms** | 0 |
| **3. Doc Search E2E**| `POST /api/v1/chat` (guideline query)| 10 | 2 | **14,100.86 ms** | **14,819.30 ms** | 0 |
| **4. TTFT (SSE Stream)**| `POST /api/v1/chat/stream` | 10 | 2 | **12,140.61 ms** | **20,545.08 ms** | 0 |

### Latency Profile Observations
- **Sub-200ms Retrieval:** Pure dense+BM25 hybrid retrieval without LLM executes in **~151 ms p50**, demonstrating high CPU efficiency of the local FAISS and BM25 index.
- **Fast SQL Query Answering:** The SQL-tool agent flow completes in **~2.8s p50**, executing SQL generation, AST validation, execution, and response synthesis.
- **LLM Synthesis & Multi-Turn Impact:** Guideline questions require multi-turn tool calling (retrieval tool call $\rightarrow$ passage injection $\rightarrow$ synthesis with clinical citations), taking ~14s under Groq's developer tier due to sequential token generation and tool round-trips.

---

## 4. System Counts & Permission Architecture

Programmatically generated from `app.openapi()` and verified against implementation source files.

- **Artifact:** [`docs/evidence/permissions_matrix.md`](evidence/permissions_matrix.md)

### Verified System Dimensions

| Dimension | Count | Verification Source |
|:---|:---:|:---|
| **Roles** | **3** | `viewer`, `pharmacist`, `admin` (`app/models.py`) |
| **Agent Tools** | **3** | `check_inventory_sql`, `search_guidelines`, `get_inventory_alerts` (`app/agent.py`) |
| **Database Models** | **7** | SQLAlchemy ORM: `Medicine`, `Batch`, `InventoryLog`, `User`, `AuditLog`, `Document`, `PendingAction` |
| **API Endpoints** | **17** | Business logic endpoints under `/api/v1/*` |
| **Ops Endpoints** | **2** | System health probes (`/health`, `/ready`) |
| **Total Endpoints** | **19** | Distinct `(method, path)` endpoints in `app.openapi()` |

### Endpoint Group Reconciliation

| Group | Endpoint Count | Methods & Routes Included |
|:---|:---:|:---|
| **Auth** | **4** | `POST /login`, `GET /me`, `GET /users`, `POST /users` |
| **Chat** | **2** | `POST /chat`, `POST /chat/stream` |
| **Inventory** | **6** | `GET /batches`, `GET /alerts`, `GET /report/daily`, `GET /fefo/recommend`, `POST /movements`, `POST /movements/{token}/confirm` |
| **Documents** | **4** | `GET /documents`, `POST /documents`, `GET /documents/search`, `DELETE /documents/{doc_id}` |
| **Admin** | **1** | `GET /admin/audit` |
| **Ops** | **2** | `GET /health`, `GET /ready` |
| **Total** | **19** | **17 API Endpoints + 2 Ops Endpoints** |

---

## 5. Reproduction Commands

To reproduce these metrics from scratch:

```powershell
# 1. Activate environment
.\.venv\Scripts\Activate.ps1

# 2. Run Test Coverage
python -m pytest --cov=app --cov-report=term-missing --cov-report=html:docs/evidence/coverage_html

# 3. Run 66-Question 3-Mode Retrieval Evaluation (REAL embeddings)
python -m eval.run_retrieval_eval

# 4. Run Latency Benchmark (4 scenarios, real embeddings, live LLM)
python scripts/latency_benchmark.py

# 5. Programmatically Re-generate Permissions Matrix & Counts
python scripts/generate_permissions_matrix.py
```
