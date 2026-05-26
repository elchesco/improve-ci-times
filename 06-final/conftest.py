"""Round 6 — final conftest.

Cumulative result of rounds 3 and 4:

  * Per-worker DATABASE_URL alignment (must run BEFORE app.main
    imports — see round 3).
  * Per-worker DB suffix so xdist workers don't fight over
    ``DROP SCHEMA``.
  * Template DB pattern with Postgres advisory lock — only used
    when xdist is active. Serial pytest takes the original
    DROP SCHEMA + create_all path.

In round 6 we ended up dropping xdist for 4 matrix shards, so this
serial-path code is what CI actually exercises. The xdist code is
still here for local ``pytest -n N`` runs.
"""

import asyncio
import os
from unittest.mock import patch, AsyncMock

import pytest
import pytest_asyncio
import sqlalchemy as sa
from httpx import AsyncClient, ASGITransport
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import (
    create_async_engine, async_sessionmaker, AsyncSession,
)


# ── DATABASE_URL alignment — MUST run before app.main import ──────


def _suffix_dburl(url: str, worker: str) -> str:
    if not url:
        return url
    if "?" in url:
        url_part, _, query = url.partition("?")
        query = f"?{query}"
    else:
        url_part, query = url, ""
    if "/" not in url_part.split("@", 1)[-1]:
        return url
    prefix, dbname = url_part.rsplit("/", 1)
    return f"{prefix}/{dbname}_{worker}{query}"


# Make the app-side engine use the test DB so background workers
# that open their own ``AsyncSessionLocal`` hit the schemaed DB.
_test_db = os.environ.get("TEST_DATABASE_URL")
if _test_db:
    os.environ["DATABASE_URL"] = _test_db

_XDIST_WORKER = os.environ.get("PYTEST_XDIST_WORKER")
if _XDIST_WORKER:
    for _env_key in ("DATABASE_URL", "TEST_DATABASE_URL"):
        _current = os.environ.get(_env_key)
        if _current:
            os.environ[_env_key] = _suffix_dburl(_current, _XDIST_WORKER)


# Now safe to import the app — engine built with the right URL.
from app.main import app  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402


# Background tasks that open their own DB sessions bypass the test
# transaction rollback — silence them so they don't bleed state
# between tests.
_bg_noop = AsyncMock()
patch("app.services.engagement_tasks.bg_record_engagement", _bg_noop).start()
patch("app.core.last_seen_middleware._update_last_seen", _bg_noop).start()


TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://appuser:testpass@localhost:5432/myapp_test",
)

test_engine = create_async_engine(
    TEST_DATABASE_URL, echo=False, poolclass=NullPool,
)
TestingSessionLocal = async_sessionmaker(
    test_engine, class_=AsyncSession, expire_on_commit=False,
)


# ── Template DB (xdist path) ──────────────────────────────────────


TEMPLATE_DB_NAME = "myapp_test_template"
_TEMPLATE_LOCK_ID = 7321456789012345


def _split_db_url(url: str) -> tuple[str, str] | None:
    if "/" not in url.split("@", 1)[-1]:
        return None
    prefix, dbname = url.rsplit("/", 1)
    if "?" in dbname:
        dbname, _, _ = dbname.partition("?")
    return prefix, dbname


async def _ensure_template_db(admin_url: str, template_url: str) -> None:
    admin_engine = create_async_engine(
        admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool,
    )
    try:
        async with admin_engine.connect() as conn:
            exists = (
                await conn.execute(
                    sa.text("SELECT 1 FROM pg_database WHERE datname = :n"),
                    {"n": TEMPLATE_DB_NAME},
                )
            ).scalar_one_or_none()
            if not exists:
                await conn.execute(
                    sa.text(f'CREATE DATABASE "{TEMPLATE_DB_NAME}"')
                )
    finally:
        await admin_engine.dispose()

    tmpl_engine = create_async_engine(template_url, poolclass=NullPool)
    try:
        async with tmpl_engine.connect() as conn:
            has_schema = (
                await conn.execute(
                    sa.text(
                        "SELECT 1 FROM information_schema.tables "
                        "WHERE table_schema = 'public' "
                        "AND table_name = 'users' LIMIT 1"
                    )
                )
            ).scalar_one_or_none()
        if not has_schema:
            async with tmpl_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
    finally:
        await tmpl_engine.dispose()


async def _clone_template_to(admin_url: str, dbname: str) -> None:
    admin_engine = create_async_engine(
        admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool,
    )
    try:
        async with admin_engine.connect() as conn:
            await conn.execute(
                sa.text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :n AND pid <> pg_backend_pid()"
                ),
                {"n": dbname},
            )
            await conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}"'))
            await conn.execute(
                sa.text(
                    f'CREATE DATABASE "{dbname}" '
                    f'TEMPLATE "{TEMPLATE_DB_NAME}"'
                )
            )
    finally:
        await admin_engine.dispose()


async def _setup_db_via_template() -> None:
    split = _split_db_url(TEST_DATABASE_URL)
    if split is None:
        return
    prefix, dbname = split
    admin_url = f"{prefix}/postgres"
    template_url = f"{prefix}/{TEMPLATE_DB_NAME}"

    admin_engine = create_async_engine(
        admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool,
    )
    try:
        async with admin_engine.connect() as conn:
            await conn.execute(
                sa.text("SELECT pg_advisory_lock(:id)"),
                {"id": _TEMPLATE_LOCK_ID},
            )
            try:
                await _ensure_template_db(admin_url, template_url)
            finally:
                await conn.execute(
                    sa.text("SELECT pg_advisory_unlock(:id)"),
                    {"id": _TEMPLATE_LOCK_ID},
                )
    finally:
        await admin_engine.dispose()

    await _clone_template_to(admin_url, dbname)


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_db():
    if os.environ.get("PYTEST_XDIST_WORKER"):
        # Parallel path: clone from a pre-built template (fast).
        await _setup_db_via_template()
        yield
        await test_engine.dispose()
        return

    # Serial path (the CI default in round 6): DROP + create_all on
    # the test DB itself. No template overhead when not using xdist.
    async with test_engine.begin() as conn:
        await conn.execute(sa.text("DROP SCHEMA public CASCADE"))
        await conn.execute(sa.text("CREATE SCHEMA public"))
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.execute(sa.text("DROP SCHEMA public CASCADE"))
        await conn.execute(sa.text("CREATE SCHEMA public"))
    await test_engine.dispose()


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    async with test_engine.connect() as conn:
        await conn.begin()
        async with AsyncSession(
            bind=conn,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        ) as session:
            yield session
        await conn.rollback()


@pytest_asyncio.fixture
async def client(db: AsyncSession):
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://localhost",
        headers={"User-Agent": "pytest-test-client"},
    ) as ac:
        yield ac
    app.dependency_overrides.clear()
