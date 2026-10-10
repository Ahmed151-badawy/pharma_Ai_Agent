import pytest

from app.sql_guard import UnsafeQueryError, validate_select

SAFE = [
    "SELECT SUM(quantity_in_stock) FROM batches WHERE medicine_id = 1",
    "SELECT b.batch_id, m.generic_name FROM batches b JOIN medicines m ON b.medicine_id = m.medicine_id "
    "WHERE b.expiration_date < CURRENT_DATE + INTERVAL '30 days'",
    "SELECT * FROM batches WHERE expiration_date <= NOW() + INTERVAL '60 days'",
    "SELECT generic_name FROM medicines WHERE LOWER(generic_name) LIKE '%amox%'",
    "SELECT date_part('day', expiration_date - CURRENT_DATE) FROM batches",
    "WITH low AS (SELECT * FROM batches WHERE quantity_in_stock < 20) SELECT * FROM low",
    "SELECT * FROM medicines WHERE storage_requirements LIKE '%Do not freeze%'",
    "SELECT m.generic_name, COUNT(*) FROM batches b JOIN medicines m USING (medicine_id) "
    "GROUP BY m.generic_name ORDER BY 2 DESC LIMIT 5",
    "SELECT * FROM public.batches",
    "SELECT 1;",
]

UNSAFE = [
    "DROP TABLE batches",
    "DELETE FROM batches",
    "UPDATE batches SET quantity_in_stock = 0",
    "INSERT INTO batches VALUES (1)",
    "SELECT 1; DROP TABLE batches",
    "SELECT 1 -- hidden",
    "SELECT /* x */ 1",
    "SELECT * FROM users",
    "SELECT password_hash FROM users",
    "SELECT * FROM audit_logs",
    "SELECT * FROM batches UNION SELECT * FROM users",
    "SELECT * FROM pg_catalog.pg_user",
    "SELECT * FROM information_schema.tables",
    "SELECT pg_sleep(10)",
    "SELECT query_to_xml('select * from users', true, true, '')",
    "WITH x AS (DELETE FROM batches RETURNING *) SELECT * FROM x",
    "SELECT * INTO newtab FROM batches",
    "SELECT * FROM batches FOR UPDATE",
    "SELECT * FROM generate_series(1, 3)",
    "COPY batches TO '/tmp/x'",
    "",
    "   ",
]


@pytest.mark.parametrize("query", SAFE)
def test_safe_queries_are_allowed(query):
    validate_select(query)


def test_trailing_semicolon_is_stripped():
    assert validate_select("SELECT 1;") == "SELECT 1"


@pytest.mark.parametrize("query", UNSAFE)
def test_unsafe_queries_are_rejected(query):
    with pytest.raises(UnsafeQueryError):
        validate_select(query)
