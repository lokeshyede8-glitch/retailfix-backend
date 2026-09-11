# =============================================================================
# RetailFix CRM -- Gunicorn Production Configuration
# Usage: gunicorn -c gunicorn.conf.py main:app
# =============================================================================
import os
import multiprocessing

# -- Workers -------------------------------------------------------------------
# WEB_CONCURRENCY env var overrides auto-calculation.
# Default formula: min(2 * cpu_count + 1, 9) for I/O-bound FastAPI apps.
# Platform recommendations:
#   Railway Free Tier (512MB RAM):  2 workers
#   Railway Starter (1GB RAM):      3 workers
#   Render Free Tier (512MB RAM):   2 workers
#   Render Standard (2GB RAM):      4–5 workers
#   2-core VPS (2GB RAM):           5 workers (2 x 2 + 1)
workers = int(os.getenv("WEB_CONCURRENCY", min(2 * multiprocessing.cpu_count() + 1, 9)))

# -- Worker class --------------------------------------------------------------
# UvicornWorker is required for ASGI / FastAPI (async support + WebSocket)
worker_class = "uvicorn.workers.UvicornWorker"

# -- Binding -------------------------------------------------------------------
host = os.getenv("HOST", "0.0.0.0")
port = os.getenv("PORT", "8001")
bind = f"{host}:{port}"

# -- Timeouts ------------------------------------------------------------------
# Timeout for individual request (seconds). Increase for long-running endpoints.
timeout = 120

# Seconds to wait for workers to finish outstanding requests on shutdown.
graceful_timeout = 30

# -- Logging -------------------------------------------------------------------
# '-' writes to stdout/stderr (captured by platform log aggregators)
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info")

# Access log format with response time
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s %(D)sus'

# -- Worker lifecycle ----------------------------------------------------------
# Restart workers after this many requests (prevents memory leaks)
max_requests = 1000
max_requests_jitter = 100  # Stagger restarts to prevent thundering herd

# -- Security ------------------------------------------------------------------
# Limit request line + headers size
limit_request_line = 8190
limit_request_fields = 100
limit_request_field_size = 8190
