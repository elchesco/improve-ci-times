# Round 2 — BuildKit cache mounts for apt + uv.
#
# Two non-obvious details:
#
# 1. Drop the ``rm -rf /var/lib/apt/lists`` we used to keep the
#    image small. With cache mounts BuildKit owns those paths and
#    cleans them up between builds — deleting them defeats the
#    cache.
#
# 2. ``sharing=locked`` serialises concurrent reads. Without it,
#    two parallel builds on the same runner can corrupt the cache.

FROM python:3.11-slim AS base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
        libpq-dev gcc curl

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system -r requirements.txt

FROM base AS dev
COPY requirements-dev.txt .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system -r requirements-dev.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM base AS production
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
