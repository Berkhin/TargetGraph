# syntax=docker/dockerfile:1
# Multi-stage build for the TargetGraph backend.
# The email-verification engine needs outbound access to the SOCKS5 proxy only;
# DNS resolution uses the container's resolver.

FROM python:3.12-slim AS base

# Fail fast, no .pyc, unbuffered stdout so JSON logs reach the Docker driver live.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# --- Dependency layer (cached independently of source) ---------------------
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# --- Application -----------------------------------------------------------
COPY app ./app

# Run as a non-root user (least privilege).
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

# Graceful shutdown: uvicorn handles SIGTERM, draining in-flight verifications.
# tini-style PID 1 handling is provided by Docker's `--init` (set in compose).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
