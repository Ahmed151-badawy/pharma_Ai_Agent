"""Database-level guarantees: read-only role, migration on a pre-existing database."""
import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from alembic import command
from tests.conftest import ROOT, migrate_fresh


def test_readonly_role_can_only_select_inventory_tables(db, settings):
    from scripts.ensure_readonly_role import main

    settings.readonly_db_password = "RoPass_12345"
    try:
        main()
        engine = create_engine(settings.readonly_sqlalchemy_url)
        with engine.connect() as conn:
            assert conn.scalar(text("SELECT count(*) FROM batches")) == 4
            for forbidden in ("SELECT * FROM users", "SELECT * FROM audit_logs",
                              "UPDATE batches SET quantity_in_stock = 0", "DELETE FROM batches"):
                with pytest.raises(DBAPIError, match="permission denied"):
                    conn.execute(text(forbidden))
                conn.rollback()
        engine.dispose()
    finally:
        settings.readonly_db_password = None


def test_sql_tool_connection_is_read_only_even_without_dedicated_role(db):
    from app.db import get_readonly_engine

    with get_readonly_engine().connect() as conn:
        with pytest.raises(DBAPIError, match="read-only transaction"):
            conn.execute(text("UPDATE batches SET quantity_in_stock = 0"))


def test_migration_adopts_a_database_created_by_the_old_script(database):
    """The very first version of the project created three tables with raw SQL (no Alembic)."""
    with database.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("""
            CREATE TABLE medicines (medicine_id SERIAL PRIMARY KEY, generic_name VARCHAR(100) NOT NULL,
                brand_name VARCHAR(100) NOT NULL, category VARCHAR(50), minimum_stock_level INT DEFAULT 50,
                storage_requirements VARCHAR(255));
            CREATE TABLE batches (batch_id VARCHAR(50) PRIMARY KEY, medicine_id INT REFERENCES medicines(medicine_id),
                supplier_name VARCHAR(100), quantity_in_stock INT NOT NULL, production_date DATE,
                expiration_date DATE NOT NULL, status VARCHAR(20) DEFAULT 'Active');
            CREATE TABLE inventory_logs (log_id SERIAL PRIMARY KEY, batch_id VARCHAR(50) REFERENCES batches(batch_id),
                transaction_type VARCHAR(20) NOT NULL, quantity_changed INT NOT NULL,
                transaction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP, handled_by VARCHAR(50));
            INSERT INTO medicines (generic_name, brand_name) VALUES ('Amoxicillin', 'Amoxil');
        """))
    try:
        command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
        with database.connect() as conn:
            assert conn.scalar(text("SELECT count(*) FROM medicines")) == 1  # existing data untouched
            assert conn.scalar(text("SELECT to_regclass('public.users') IS NOT NULL"))
            assert conn.scalar(text("SELECT to_regclass('public.audit_logs') IS NOT NULL"))
    finally:
        migrate_fresh()


def test_downgrade_keeps_core_inventory_tables(database):
    try:
        command.downgrade(Config(str(ROOT / "alembic.ini")), "base")
        with database.connect() as conn:
            assert conn.scalar(text("SELECT to_regclass('public.users') IS NULL"))
            assert conn.scalar(text("SELECT to_regclass('public.batches') IS NOT NULL"))
    finally:
        migrate_fresh()
