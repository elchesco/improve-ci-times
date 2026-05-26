# Round 1 — drop pip for uv.
#
# COPY the uv binary from the official multi-stage image so the
# version is pinned and reproducible. ENV vars set so uv never tries
# to download its own Python (must use the system one) and uses
# copy-mode linking (works correctly with apt-installed Python).

FROM python:3.11-slim AS base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc curl \
    && rm -rf /var/lib/apt/lists/*

# uv (Astral) — 10-100x faster than pip for resolving + installing.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

COPY requirements.txt .
RUN uv pip install --system --no-cache-dir -r requirements.txt

FROM base AS dev
COPY requirements-dev.txt .
RUN uv pip install --system --no-cache-dir -r requirements-dev.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM base AS production
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
