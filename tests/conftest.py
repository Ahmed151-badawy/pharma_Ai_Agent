import os
import shutil
import tempfile
from pathlib import Path

# Environment must be set BEFORE the app is imported.
_INDEX_DIR = tempfile.mkdtemp(prefix="faiss_test_")
os.environ.update({
    "JWT_SECRET": "test-secret-test-secret-12345678",
    "EMBEDDINGS_BACKEND": "fake",
    "FAISS_INDEX_DIR": _INDEX_DIR,
    "ADMIN_USERNAME": "admin",
    "ADMIN_PASSWORD": "admin-pass-123",
    "RATE_LIMIT_ENABLED": "false",
    "LOG_JSON": "false",
    "LOG_LEVEL": "WARNING",
})
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/pharma_test")
os.environ["GROQ_API_KEY"] = ""
os.environ.pop("READONLY_DB_PASSWORD", None)

import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from alembic import command  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import SessionLocal, get_engine  # noqa: E402
from app.rag import get_kb  # noqa: E402
from app.ratelimit import limiter  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def migrate_fresh() -> None:
    """Empty the schema and rebuild it with Alembic (so every test run also tests the migration)."""
    with get_engine().begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")


@pytest.fixture(scope="session")
def database():
    try:
        get_engine().connect().close()
    except OperationalError:
        if os.getenv("CI"):
            raise
        pytest.skip("PostgreSQL not reachable. Set DATABASE_URL to run the database tests.")
    migrate_fresh()
    return get_engine()


@pytest.fixture
def db(database):
    """Clean, seeded database + empty knowledge base for every test."""
    from scripts.seed_demo_data import seed

    with database.begin() as conn:
        conn.execute(text(
            "TRUNCATE inventory_logs, batches, medicines, users, audit_logs, documents, pending_actions "
            "RESTART IDENTITY CASCADE"))
    with SessionLocal() as session:
        seed(session)
    shutil.rmtree(_INDEX_DIR, ignore_errors=True)
    get_kb.cache_clear()
    limiter.reset()
    yield database


@pytest.fixture
def kb():
    shutil.rmtree(_INDEX_DIR, ignore_errors=True)
    get_kb.cache_clear()
    knowledge_base = get_kb()
    knowledge_base.ensure_seed()
    return knowledge_base


@pytest.fixture
def client(db):
    from app.main import app

    with TestClient(app) as test_client:  # runs the lifespan: creates the admin, indexes the seed document
        yield test_client
    app.dependency_overrides.clear()


def login(client: TestClient, username: str, password: str) -> dict:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def admin_headers(client):
    return login(client, "admin", "admin-pass-123")


@pytest.fixture
def make_user(client, admin_headers):
    def _make(username: str, role: str, password: str = "password-123") -> dict:
        response = client.post("/api/v1/auth/users", headers=admin_headers,
                               json={"username": username, "password": password, "role": role})
        assert response.status_code == 201, response.text
        return login(client, username, password)

    return _make


@pytest.fixture
def pharmacist_headers(make_user):
    return make_user("pat", "pharmacist")


@pytest.fixture
def viewer_headers(make_user):
    return make_user("vic", "viewer")


@pytest.fixture
def settings():
    return get_settings()
