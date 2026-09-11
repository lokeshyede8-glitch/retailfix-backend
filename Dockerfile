# =============================================================================
# RetailFix CRM -- Backend Dockerfile
# Multi-stage build: slim production image, non-root user.
# =============================================================================

# -- Stage 1: Build dependencies ----------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies into a virtual environment
COPY requirements.txt .
RUN python -m venv /app/.venv && \
    /app/.venv/bin/pip install --upgrade pip && \
    /app/.venv/bin/pip install --no-cache-dir -r requirements.txt

# -- Stage 2: Runtime image ----------------------------------------------------
FROM python:3.12-slim AS runtime

WORKDIR /app

# Runtime system deps only (libpq for psycopg2)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 --ingroup appgroup --no-create-home appuser

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application source (exclude dev files)
COPY --chown=appuser:appgroup . .

# Remove development files from production image
RUN rm -f quotation.db verify_apis.py verify_apis_fix.py \
          write_frontend.py write_followup_jsx.py run_backend_tests.py \
          find_pgadmin_db.py backend_run.log pg_log.txt && \
    rm -rf venv __pycache__ .git pg_data

# Use virtual environment
ENV PATH="/app/.venv/bin:"

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')" || exit 1

# Production start command:
# - Runs alembic migrations before starting the server
# - Uses gunicorn with uvicorn workers for multi-worker concurrency
CMD ["sh", "-c", "alembic upgrade head && gunicorn main:app -k uvicorn.workers.UvicornWorker --workers \ --bind 0.0.0.0:\ --timeout 120 --graceful-timeout 30 --access-logfile - --error-logfile -"]
