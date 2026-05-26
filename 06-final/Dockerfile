# Round 6 — final Dockerfile (cumulative: uv + BuildKit cache mounts +
# apt-get upgrade for latest debian security patches).

FROM python:3.11-slim AS base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# ``apt-get upgrade`` pulls the latest debian point-release security
# patches (e.g. deb13u3 → deb13u4) without waiting for Astral to
# rebuild the python:slim base. Trivy weekly scan ratchets us off
# CRITICAL CVEs in libgnutls/openssl as soon as Debian publishes
# them.
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
