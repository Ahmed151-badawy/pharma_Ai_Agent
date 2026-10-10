"""Create/refresh a Postgres role that can ONLY read the three inventory tables.

The agent's SQL tool connects with this role when READONLY_DB_PASSWORD is set, so even a perfect
prompt-injection could never read `users`, `audit_logs` or write anything. Needs a DB user that is
allowed to create roles (the master user on RDS is).
"""
import re
import sys

from sqlalchemy import text

from app.config import get_settings
from app.db import get_engine


def main() -> None:
    settings = get_settings()
    password = settings.readonly_db_password
    if not password:
        print("READONLY_DB_PASSWORD not set: skipping read-only role.")
        return
    user = settings.readonly_db_user
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", user):
        sys.exit("READONLY_DB_USER must match [a-z_][a-z0-9_]*")
    if not re.fullmatch(r"[A-Za-z0-9_.@#^~+=!-]{8,128}", password):
        sys.exit("READONLY_DB_PASSWORD must be 8-128 chars from A-Z a-z 0-9 _ . @ # ^ ~ + = ! -")

    with get_engine().begin() as conn:
        exists = conn.scalar(text("SELECT 1 FROM pg_roles WHERE rolname = :u"), {"u": user})
        conn.execute(text(f"{'ALTER' if exists else 'CREATE'} ROLE {user} LOGIN PASSWORD '{password}'"))
        database = conn.scalar(text("SELECT current_database()"))
        conn.execute(text(f'GRANT CONNECT ON DATABASE "{database}" TO {user}'))
        conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {user}"))
        conn.execute(text(f"GRANT SELECT ON medicines, batches, inventory_logs TO {user}"))
    print(f"✓ Read-only role '{user}' is ready.")


if __name__ == "__main__":
    main()
