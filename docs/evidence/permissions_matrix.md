# Programmatic Permission Matrix & API Endpoints

Generated programmatically via `app.openapi()` and route dependency inspection.

## System Summary Counts

| Dimension | Count | Details / Verification Source |
|:---|:---:|:---|
| **Roles** | **3** | `viewer`, `pharmacist`, `admin` (`app/models.py`) |
| **Agent Tools** | **3** | `check_inventory_sql`, `search_guidelines`, `get_inventory_alerts` (`app/agent.py`) |
| **Database Models** | **7** | SQLAlchemy declarative models in `app/models.py` |
| **API Endpoints** | **17** | Functional business endpoints (`/api/v1/*`) |
| **Ops Endpoints** | **2** | Operational health/readiness probes (`/health`, `/ready`) |
| **Total Endpoints** | **19** | Exact distinct (method, path) pairs in `app.openapi()` |

## Endpoint Group Breakdown & Reconciliation

> **Discrepancy Resolution:**
> The repository snapshot previously reported *Inventory (5)* and *Documents (3)*, which summed to 15 API endpoints + 2 ops = 17 endpoints.
> Programmatic inspection of `app.openapi()` proves the actual counts are **Inventory (6)** and **Documents (4)**, totaling **17 API endpoints + 2 ops = 19 endpoints**.

| Group / Tag | OpenAPI Route Count | Endpoints Included |
|:---|:---:|:---|
| **Auth** | **4** | `/login`, `/me`, `/users` (GET), `/users` (POST) |
| **Chat** | **2** | `/chat`, `/chat/stream` |
| **Inventory** | **6** | `/batches`, `/alerts`, `/report/daily`, `/fefo/recommend`, `/movements`, `/movements/{token}/confirm` |
| **Documents** | **4** | `/documents` (GET), `/documents` (POST), `/documents/search`, `/documents/{doc_id}` (DELETE) |
| **Admin** | **1** | `/admin/audit` |
| **Ops** | **2** | `/health`, `/ready` |
| **Total** | **19** | **17 API Endpoints + 2 Ops Endpoints** |

## Role Permission Matrix

| Group | HTTP Method & Endpoint | viewer | pharmacist | admin | Minimum Required Role |
|:---|:---|:---:|:---:|:---:|:---|
| Auth | `POST /api/v1/auth/login` | open | open | open | `open` |
| Auth | `GET /api/v1/auth/me` | ✅ | ✅ | ✅ | `viewer` |
| Auth | `GET /api/v1/auth/users` | ❌ | ❌ | ✅ | `admin` |
| Auth | `POST /api/v1/auth/users` | ❌ | ❌ | ✅ | `admin` |
| Chat | `POST /api/v1/chat` | ✅ | ✅ | ✅ | `viewer` |
| Chat | `POST /api/v1/chat/stream` | ✅ | ✅ | ✅ | `viewer` |
| Inventory | `GET /api/v1/inventory/alerts` | ✅ | ✅ | ✅ | `viewer` |
| Inventory | `GET /api/v1/inventory/batches` | ✅ | ✅ | ✅ | `viewer` |
| Inventory | `GET /api/v1/inventory/fefo/recommend` | ✅ | ✅ | ✅ | `viewer` |
| Inventory | `POST /api/v1/inventory/movements` | ❌ | ✅ | ✅ | `pharmacist` |
| Inventory | `POST /api/v1/inventory/movements/{token}/confirm` | ❌ | ✅ | ✅ | `pharmacist` |
| Inventory | `GET /api/v1/inventory/report/daily` | ✅ | ✅ | ✅ | `viewer` |
| Documents | `GET /api/v1/documents` | ✅ | ✅ | ✅ | `viewer` |
| Documents | `POST /api/v1/documents` | ❌ | ❌ | ✅ | `admin` |
| Documents | `GET /api/v1/documents/search` | ✅ | ✅ | ✅ | `viewer` |
| Documents | `DELETE /api/v1/documents/{doc_id}` | ❌ | ❌ | ✅ | `admin` |
| Admin | `GET /api/v1/admin/audit` | ❌ | ❌ | ✅ | `admin` |
| Ops | `GET /health` | open | open | open | `open` |
| Ops | `GET /ready` | open | open | open | `open` |

## Audit & Security Observations
- **Least Privilege:** Write operations (`/inventory/movements`, `/documents` POST/DELETE, `/auth/users`) strictly require `pharmacist` or `admin`.
- **Agent Read-Only Boundary:** The LangGraph ReAct agent operates through read-only tools and has no route access to create or confirm stock movements.
- **Authentication:** All protected endpoints enforce Bearer JWT tokens validated via `app/auth.py:get_current_user` against active database user rows.
