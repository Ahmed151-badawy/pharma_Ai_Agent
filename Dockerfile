FROM python:3.10-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/home/app/.cache/huggingface

# System dependencies for the PostgreSQL driver (psycopg2)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# CPU-only PyTorch. The "+cpu" tag exists only on the PyTorch CPU index, so pip cannot pick the huge
# CUDA build from PyPI. PyPI stays available for torch's regular dependencies.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --default-timeout=120 --retries 10 "torch==2.14.1+cpu" \
    --extra-index-url https://download.pytorch.org/whl/cpu

COPY requirements.lock requirements.txt requirements-base.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --default-timeout=120 --retries 10 -c requirements.lock -r requirements.txt

# Run as a non-root user
RUN useradd --create-home --uid 1000 app && chown app:app /app
COPY --chown=app:app . .
USER app

# Build the FAISS index now. This also pre-downloads the embedding model into the image,
# so the first request is fast and the container needs no internet access for it.
RUN python -m scripts.build_index

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 CMD ["python", "scripts/healthcheck.py"]

# Entrypoint: alembic migrations -> optional read-only role / demo data -> uvicorn
CMD ["sh", "scripts/start.sh"]
