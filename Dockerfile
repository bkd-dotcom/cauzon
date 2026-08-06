# Container for the Cauzon API.
#
# Targets Cloud Run: listens on $PORT, binds 0.0.0.0, runs as non-root, and holds
# no state (a fresh agent per request), so it scales to zero and back safely.
# Also runs anywhere else that takes a container.

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependency layer first, so source edits don't reinstall the world.
COPY pyproject.toml README.md ./
COPY agent/ ./agent/
# `[datahub]` pulls the MCP client. It is what makes CAUZON_DATAHUB_BACKEND=mcp
# possible, so it belongs in the image even when a deployment starts on mock.
RUN pip install --upgrade pip && pip install ".[datahub]"

COPY backend/ ./backend/

RUN useradd --create-home --uid 10001 cauzon
USER cauzon

# Cloud Run injects PORT; 8080 is its default and a sane local fallback.
ENV PORT=8080
EXPOSE 8080

# Single worker: investigations are short and the process is stateless, so
# concurrency is Cloud Run's job, not uvicorn's.
CMD ["sh", "-c", "exec uvicorn backend.main:app --host 0.0.0.0 --port ${PORT}"]
