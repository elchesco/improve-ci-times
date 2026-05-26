"""Test conftest — starting point.

Sync engine fixtures pointing at a real Postgres (via TEST_DATABASE_URL).
``setup_db`` runs ``DROP SCHEMA public CASCADE`` once at session start
and again at session end so every CI run starts clean. ``db`` wraps
each test in a transaction that rolls back at teardown for isolation.

The DROP SCHEMA pattern is the one that broke under xdist (multiple
workers dropping each other's schemas mid-run). See round 3.
"""

import asyncio
import os

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import (
    create_async_engine, async_sessionmaker, AsyncSession,
)

from app.main import app  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402


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


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_db():
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
