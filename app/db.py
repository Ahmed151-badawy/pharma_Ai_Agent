from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().sqlalchemy_url, pool_pre_ping=True, pool_size=5, max_overflow=5)


@lru_cache
def get_readonly_engine() -> Engine:
    """Engine used ONLY by the agent's SQL tool: read-only transactions and a 5 s statement timeout."""
    return create_engine(
        get_settings().readonly_sqlalchemy_url,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=2,
        connect_args={"options": "-c default_transaction_read_only=on -c statement_timeout=5000"},
    )


@lru_cache
def _session_factory() -> sessionmaker:
    return sessionmaker(get_engine(), expire_on_commit=False)


def SessionLocal() -> Session:  # noqa: N802 (kept CamelCase: it behaves like a class)
    return _session_factory()()


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one database session per request."""
    with SessionLocal() as session:
        yield session
