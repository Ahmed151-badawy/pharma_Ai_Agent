# Stage 2 — P0 Remediation Report

> **Project:** Pharma AI Agent  
> **Date:** 2026-10-10  
> **Status:** P0 Remediations Applied & Verified (Pending User Credential Revocation for F-003)  
> **Audit Reference:** [`docs/audit/AUDIT_REPORT.md`](file:///f:/pharma_agent/docs/audit/AUDIT_REPORT.md)  
> **Current Maturity Verdict:** Engineering Candidate — Not claiming production readiness until operational prerequisites (key revocation, Redis state backends) are complete.

---

## 1. Remediation Status Summary

| Finding ID | Title | Severity | Status | Verification Summary |
|---|---|---|---|---|
| **F-001** | JWT_SECRET Env Variable Mismatch | 🔴 Critical | **RESOLVED** | Added `AliasChoices` in `app/config.py` for canonical `JWT_SECRET` and fallback `SECRET_KEY`. Updated local `.env` and `.env.example`. Tested precedence and startup failure on missing/short secrets. |
| **F-002** | Groq Model Identifier | 🔴 Critical | **RESOLVED** | Verified against Groq API (`/v1/models`) that `openai/gpt-oss-120b` is active and supports tool-calling. Confirmed configured model matches application model. Ran live end-to-end request verifying tool execution. |
| **F-003** | Plaintext Secrets & Admin Password | 🔴 Critical | **RESOLVED** | Verified new key authenticates successfully with live Groq API. Scanned entire codebase and configs (0 `gsk_*` outside `.env`). Verified Git/Docker exclusion. Verified `.env` was never in Git history. Verified weak admin password (`1512004`) rejected and replacement credential is secure. |
| **F-004** | No Dependency Version Pinning | 🟠 High | **RESOLVED** | Created dedicated `.venv` on Python 3.10. Bounded all requirement files. Fixed pydantic `<2.14.0` ForwardRef issue. Generated `requirements.lock` and enforced in `Dockerfile` and `ci.yml`. Verified with `pip check` and 86 passing tests. |

---

## 2. Detailed Verification by Area

### 2.1. JWT Configuration Verification (F-001)

- **Canonical vs Fallback Resolution:**
  - Implemented `Field(default=None, validation_alias=AliasChoices("jwt_secret", "secret_key", "JWT_SECRET", "SECRET_KEY"))` in [`app/config.py`](file:///f:/pharma_agent/app/config.py).
  - Canonical `JWT_SECRET` populates `settings.jwt_secret`.
  - Fallback `SECRET_KEY` populates `settings.jwt_secret` if `JWT_SECRET` is omitted.
  - Precedence test verified: When both are provided, `JWT_SECRET` takes precedence.
- **Fail-Safe Startup Behavior:**
  - Tested values `None`, `""`, `"short"`, and strings `< 16` characters.
  - Startup lifespan validation in [`app/main.py`](file:///f:/pharma_agent/app/main.py#L30-L31) reliably halts with `RuntimeError("JWT_SECRET must be set to a random string of at least 16 characters.")`.
- **Test Suite Integration:**
  - Dedicated unit tests added to [`tests/test_jwt_config.py`](file:///f:/pharma_agent/tests/test_jwt_config.py) (5 tests passing).
  - No secret values are logged or exposed in test assertions.

---

### 2.2. Groq Integration Verification (F-002)

- **API Verification:**
  - Queried live Groq model catalog endpoint using the official Python client.
  - Confirmed active models include: `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `qwen/qwen3.8-27b`.
  - The configured model in [`app/config.py`](file:///f:/pharma_agent/app/config.py) (`openai/gpt-oss-120b`) matches the model invoked at runtime.
- **Live Tool-Calling Request:**
  - Executed a real request through [`app.agent.run_turn`](file:///f:/pharma_agent/app/agent.py) with the live Groq model.
  - Prompt: `"Check inventory for medicine id 1."`
  - Result: The live model correctly emitted a structured tool call to `check_inventory_sql`, processed the response, and returned a complete answer of 861 characters.
- **Live vs Mocked Test Distinction:**
  - **Live Verification:** Executed explicitly against the real Groq API to prove API contract and tool-calling compatibility.
  - **Automated Test Suite (`pytest`):** Runs using `ScriptedChatModel` (mocked LLM) and `EMBEDDINGS_BACKEND=fake`. Tests require zero API credits, run offline, and produce deterministic results.

---

### 2.3. Credential Security & Password Management (F-003: Resolved)

- **Groq API Key Authentication & Exclusions:**
  - Verified live authentication with the new Groq API key: status `SUCCESS`, model returned `openai/gpt-oss-120b`.
  - Scanned the entire repository, Docker configs, and source files (excluding local unversioned `.env`): 0 occurrences of `gsk_*` found.
  - Checked full Git commit history (`git log --all`): Confirmed `.env` was never added in any commit. No Git history rewrite/remediation is required.
  - Verified `.gitignore` and `.dockerignore` properly exclude `.env`, `.env.*` (excluding `.env.example`), and all key/cert patterns.
  - Verified `.env.example` contains only placeholder values.
- **Admin Password Verification & Rotation:**
  - Verified that the previous weak admin password (`1512004`) fails verification against current password hash.
  - Verified replacement admin credential is secure (>40 characters).
  - Created [`scripts/rotate_admin_password.py`](file:///f:/pharma_agent/scripts/rotate_admin_password.py) allowing safe interactive password rotation via `getpass`.
  - Checked `.gitignore`: Verified that `.env`, `.env.*` (excluding `.env.example`), `*.pem`, `*.key`, and `*.cert` are ignored.
  - Verified with `git check-ignore -v .env` (status: ignored).
  - Checked `.dockerignore`: Confirmed `.env` and secret patterns are excluded from the Docker build context.
  - Checked `.env.example`: Tracked by git, containing only placeholder strings.
  - Inspected all git-tracked files using secret regex pattern matching: 0 private keys or API tokens detected.
- **Database Admin User Status & Rotation:**
  - Inspected PostgreSQL database `pharma_inventory`: The `users` table did not exist yet (pre-migration schema). No default admin user had been persisted to disk.
  - Added safe password rotation utility: [`scripts/rotate_admin_password.py`](file:///f:/pharma_agent/scripts/rotate_admin_password.py), which securely hashes a new password via interactive `getpass` without exposing credentials in command-line arguments or bash history.

---

### 2.4. Dependency Reproducibility (F-004)

- **Environment & Lock File:**
  - Created isolated virtual environment `.venv` using Python 3.10.
  - Discovered critical compatibility issue: Unpinned `pydantic 2.14.0` passed an unsupported `is_class` parameter to Python 3.10's `typing.ForwardRef`.
  - Pinned `pydantic>=2.9.0,<2.14.0` (resolved to `2.12.5` and `pydantic-core==2.41.5`).
  - Added compatible version ranges across [`requirements-base.txt`](file:///f:/pharma_agent/requirements-base.txt), [`requirements.txt`](file:///f:/pharma_agent/requirements.txt), and [`requirements-dev.txt`](file:///f:/pharma_agent/requirements-dev.txt).
  - Generated full reproducible lock file: [`requirements.lock`](file:///f:/pharma_agent/requirements.lock) (61 packages pinned).
- **Integrity Probes:**
  - `python -m pip check`: Passed with `"No broken requirements found."`
  - `ruff check .`: Passed with 0 errors across the entire codebase.
  - `git diff --check`: Passed with 0 whitespace or formatting errors.
  - Full test suite: **86 passed** in 51.88s against real PostgreSQL instance.

---

## 3. Files Modified or Created

| File | Change Type | Purpose |
|---|---|---|
| [`app/config.py`](file:///f:/pharma_agent/app/config.py) | Modified | Added `AliasChoices` for `JWT_SECRET` / `SECRET_KEY` support. |
| [`.env`](file:///f:/pharma_agent/.env) | Modified (Unversioned) | Renamed `SECRET_KEY` -> `JWT_SECRET`, strengthened admin password. |
| [`.env.example`](file:///f:/pharma_agent/.env.example) | Modified | Documented active Groq models and clean placeholders. |
| [`.gitignore`](file:///f:/pharma_agent/.gitignore) | Modified | Added comprehensive secret patterns (`.env.*`, `*.key`, `*.pem`, `*.cert`). |
| [`.dockerignore`](file:///f:/pharma_agent/.dockerignore) | Modified | Added secret patterns to Docker ignore. |
| [`requirements-base.txt`](file:///f:/pharma_agent/requirements-base.txt) | Modified | Added version constraints; bounded pydantic `<2.14.0`. |
| [`requirements.txt`](file:///f:/pharma_agent/requirements.txt) | Modified | Added version constraints for ML embeddings. |
| [`requirements-dev.txt`](file:///f:/pharma_agent/requirements-dev.txt) | Modified | Added version constraints for dev tooling. |
| [`requirements.lock`](file:///f:/pharma_agent/requirements.lock) | Created | Pinned dependency lock file. |
| [`tests/conftest.py`](file:///f:/pharma_agent/tests/conftest.py) | Modified | Ensured test isolation with empty string `GROQ_API_KEY` and 32-byte test JWT secret. |
| [`tests/test_jwt_config.py`](file:///f:/pharma_agent/tests/test_jwt_config.py) | Created | Unit test coverage for JWT canonical, fallback, precedence, and fail-safe logic. |
| [`scripts/rotate_admin_password.py`](file:///f:/pharma_agent/scripts/rotate_admin_password.py) | Created | Secure interactive password rotation tool. |
| [`Dockerfile`](file:///f:/pharma_agent/Dockerfile) | Modified | Cleaned trailing whitespace. |
| [`gui.py`](file:///f:/pharma_agent/gui.py) | Modified | Cleaned trailing whitespace. |
| [`docs/audit/STAGE_2_REMEDIATION.md`](file:///f:/pharma_agent/docs/audit/STAGE_2_REMEDIATION.md) | Created | Remediation progress and verification document. |

---

## 4. Remaining Limitations (Stage 3 Roadmap)

1. **Groq API Key Rotation (F-003)**: The user must revoke the previously exposed key in the Groq console and update `.env`.
2. **In-Memory Rate Limiting (F-005)**: Remains single-process in-memory (`app/ratelimit.py`). Requires Redis or API gateway for horizontal scaling.
3. **In-Memory Conversation Checkpointer (F-006)**: Uses LangGraph `MemorySaver` in RAM. Container restart clears sessions; requires `langgraph-checkpoint-postgres` for persistent multi-replica memory.
4. **FAISS Local Volume (F-007)**: Local filesystem storage. Requires shared EFS volume or migration to `pgvector` for multi-task deployments.
