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

RUN addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 --ingroup appgroup --no-create-home appuser

COPY --from=builder /app/.venv /app/.venv

COPY --chown=appuser:appgroup . .

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

ENV PATH="/app/.venv/bin:/usr/local/bin:/usr/bin:/bin"

USER appuser

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')" || exit 1

    
CMD ["sh", "-c", "/app/.venv/bin/alembic upgrade head && exec /app/.venv/bin/gunicorn main:app -k uvicorn.workers.UvicornWorker --workers 2 --bind 0.0.0.0:${PORT:-8001} --timeout 120 --graceful-timeout 30 --access-logfile - --error-logfile -"]