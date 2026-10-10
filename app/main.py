import logging
import re
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import __version__
from app.auth import ensure_admin
from app.config import get_settings
from app.db import SessionLocal
from app.inventory import InventoryError
from app.logging_conf import request_id_var, setup_logging
from app.rag import IngestError, get_kb
from app.routers import admin, auth, chat, documents
from app.routers import inventory as inventory_router

logger = logging.getLogger("pharma-agent")
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_json)
    if not settings.jwt_secret or len(settings.jwt_secret) < 16:
        raise RuntimeError("JWT_SECRET must be set to a random string of at least 16 characters.")
    with SessionLocal() as session:
        ensure_admin(session)
    get_kb().ensure_seed()
    logger.info("Pharma agent %s started", __version__)
    yield


app = FastAPI(
    title="Pharma AI Agent",
    version=__version__,
    description="LangGraph agent over pharmacy inventory (PostgreSQL) and guidelines (FAISS + BM25), "
                "with JWT auth, conversation memory, streaming and source citations.",
    lifespan=lifespan,
)

_origins = [o.strip() for o in get_settings().cors_origins.split(",") if o.strip()]
if _origins:
    app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_credentials=False,
                       allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def request_context(request: Request, call_next):
    incoming = request.headers.get("X-Request-ID", "")
    request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex[:16]
    token = request_id_var.set(request_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled error")
        response = JSONResponse({"detail": "Internal server error."}, status_code=500)
    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    response.headers["X-Request-ID"] = request_id
    logger.info(f"{request.method} {request.url.path} -> {response.status_code} ({duration_ms} ms)",
                extra={"extra_fields": {"method": request.method, "path": request.url.path,
                                        "status": response.status_code, "duration_ms": duration_ms}})
    request_id_var.reset(token)
    return response


@app.exception_handler(InventoryError)
async def inventory_error_handler(_: Request, exc: InventoryError):
    return JSONResponse({"detail": exc.message}, status_code=exc.status_code)


@app.exception_handler(IngestError)
async def ingest_error_handler(_: Request, exc: IngestError):
    return JSONResponse({"detail": exc.message}, status_code=exc.status_code)


app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(inventory_router.router)
app.include_router(documents.router)
app.include_router(admin.router)


@app.get("/health", tags=["ops"])
def health():
    """Liveness probe (Docker / ECS load balancer): the process is up."""
    return {"status": "healthy", "service": "pharma-agent-backend", "version": __version__}


@app.get("/ready", tags=["ops"])
def ready():
    """Readiness probe: database reachable and knowledge base loaded."""
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
        chunks = get_kb().chunk_count
    except Exception:
        logger.exception("Readiness check failed")
        return JSONResponse({"status": "not_ready"}, status_code=503)
    return {"status": "ready", "knowledge_base_chunks": chunks}
