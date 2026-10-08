# Use an official, lightweight Python image
FROM python:3.10-slim

# Set the working directory inside the container
WORKDIR /app

# System dependencies for PostgreSQL driver (psycopg2) and native builds
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install CPU-only PyTorch.
# The "+cpu" local version tag only exists on the PyTorch CPU index, so pip
# cannot silently pick the huge CUDA build from PyPI. PyPI stays available
# (extra-index-url) for torch's regular dependencies (filelock, typing-extensions, ...).
RUN pip install --no-cache-dir "torch==2.14.1+cpu" \
    --extra-index-url https://download.pytorch.org/whl/cpu

# Install the remaining Python dependencies
# (torch is already satisfied, so pip will not replace it)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Expose the port FastAPI runs on
EXPOSE 8000

# Run the FastAPI server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
