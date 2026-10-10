#!/bin/sh
# Container entrypoint: migrate the database, optionally seed demo data, then start the API.
set -e
alembic upgrade head
python -m scripts.ensure_readonly_role
if [ "${SEED_DEMO_DATA:-false}" = "true" ]; then
  python -m scripts.seed_demo_data
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers
