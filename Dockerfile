# =============================================================================
# RetailFix CRM - Production Dockerfile
# =============================================================================

FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN python -m venv /app/.venv && \
    /app/.venv/bin/pip install --upgrade pip && \
    /app/.venv/bin/pip install --no-cache-dir -r requirements.txt


# =============================================================================
# Runtime
# =============================================================================

FROM python:3.12-slim AS runtime

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Create dedicated non-root user with an explicit home directory
# (Prevents Debian default /nonexistent home directory permission errors)
RUN addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 --ingroup appgroup --home /home/appuser appuser

ENV HOME=/home/appuser \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=builder /app/.venv /app/.venv

# Copy application source code with proper ownership
COPY --chown=appuser:appgroup . .

# Ensure /app/uploads and /home/appuser exist, are owned by appuser, and writable
RUN mkdir -p /app/uploads /home/appuser && \
    chown -R appuser:appgroup /app/uploads /home/appuser && \
    chmod -R 775 /app/uploads /home/appuser

RUN rm -f \
    quotation.db \
    verify_apis.py \
    verify_apis_fix.py \
    write_frontend.py \
    write_followup_jsx.py \
    run_backend_tests.py \
    find_pgadmin_db.py \
    backend_run.log \
    pg_log.txt && \
    rm -rf \
    venv \
    __pycache__ \
    .git \
    pg_data

USER appuser

EXPOSE 8001

# Dynamic HEALTHCHECK respecting Railway's PORT environment variable
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request, os; p = os.environ.get('PORT', '8001'); urllib.request.urlopen(f'http://127.0.0.1:{p}/health')" || exit 1

CMD ["sh", "-c", "/app/.venv/bin/alembic upgrade head && exec /app/.venv/bin/gunicorn -c gunicorn.conf.py main:app"]