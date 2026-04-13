# === Stage 1: Build — install dependencies only ===
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build deps (gcc for C extensions, libpq-dev for asyncpg)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy pyproject.toml and extract+install only the dependencies
COPY pyproject.toml .
RUN python -c "import tomllib; data=tomllib.load(open('pyproject.toml','rb')); print('\n'.join(data['project']['dependencies']))" > /tmp/requirements.txt && \
    pip install --no-cache-dir --prefix=/install -r /tmp/requirements.txt

# === Stage 2: Runtime ===
FROM python:3.11-slim

# Install runtime deps (libpq for asyncpg, curl for healthcheck)
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq5 curl && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN adduser --disabled-password --gecos "" appuser

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
WORKDIR /app
COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini ./alembic.ini

# Set Python path so app module is importable
ENV PYTHONPATH="/app/src"
ENV PYTHONUNBUFFERED=1

# Switch to non-root
USER appuser

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=15s \
    CMD curl -f http://localhost:8000/health || exit 1

# Run with uvicorn — graceful shutdown timeout matches our middleware (60s)
CMD ["python", "-m", "uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--timeout-graceful-shutdown", "60", \
     "--log-level", "info"]
