"""Validation layer for SQL written by the LLM.

The agent may only run ONE read-only SELECT over an allow-list of tables. The query is parsed with
sqlglot (not regexes), so tricks like comments, stacked statements, schema-qualified catalog tables,
data-modifying CTEs or `query_to_xml('select ...')` are rejected.

This is defence in depth: the SQL tool also uses a read-only transaction, a statement timeout and,
when configured, a dedicated Postgres role that can only SELECT from the allowed tables.
"""
import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

ALLOWED_TABLES = frozenset({"medicines", "batches", "inventory_logs"})

_SET_OPERATION = getattr(exp, "SetOperation", exp.Union)
_FORBIDDEN_NODES = tuple(
    getattr(exp, name)
    for name in ("Insert", "Update", "Delete", "Drop", "Create", "Alter", "Command", "Merge", "Copy", "Into", "Lock")
    if hasattr(exp, name)
)


class UnsafeQueryError(ValueError):
    """Raised when a query is not a safe, read-only SELECT."""


def validate_select(query: str, allowed_tables: frozenset[str] = ALLOWED_TABLES) -> str:
    """Return the cleaned query if it is safe, otherwise raise UnsafeQueryError."""
    if not query or not query.strip():
        raise UnsafeQueryError("Empty query.")

    cleaned = query.strip().rstrip(";").strip()
    if "--" in cleaned or "/*" in cleaned:
        raise UnsafeQueryError("SQL comments are not allowed.")

    try:
        statements = [s for s in sqlglot.parse(cleaned, read="postgres") if s is not None]
    except SqlglotError as exc:
        raise UnsafeQueryError("Could not parse the SQL query.") from exc

    if len(statements) != 1:
        raise UnsafeQueryError("Only a single statement is allowed.")
    stmt = statements[0]

    if not isinstance(stmt, (exp.Select, _SET_OPERATION)):
        raise UnsafeQueryError("Only SELECT queries are allowed.")
    if stmt.find(*_FORBIDDEN_NODES):
        raise UnsafeQueryError("The query contains a forbidden operation.")

    # Functions sqlglot does not recognise (pg_sleep, query_to_xml, dblink, ...) are rejected.
    for func in stmt.find_all(exp.Anonymous):
        raise UnsafeQueryError(f"Function not allowed: {func.name}")

    cte_names = {cte.alias_or_name.lower() for cte in stmt.find_all(exp.CTE)}
    for table in stmt.find_all(exp.Table):
        name = table.name.lower()
        if not name:
            raise UnsafeQueryError("Unsupported FROM source.")
        if table.db and table.db.lower() != "public":
            raise UnsafeQueryError(f"Schema-qualified tables are not allowed: {table.db}.{name}")
        if name in cte_names and not table.db:
            continue
        if name not in allowed_tables:
            raise UnsafeQueryError(f"Table not allowed: {name}. Allowed: {', '.join(sorted(allowed_tables))}")

    return cleaned
