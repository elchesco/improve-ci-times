"""Round 4 — Postgres template database.

Replaces the per-worker DROP SCHEMA + create_all (~5s per worker) with
a single shared template DB built once + cloned per worker (~100ms
per clone via ``CREATE DATABASE ... TEMPLATE``).

A Postgres advisory lock serialises template creation across xdist
workers. The first worker in builds the template; the others wait,
then clone.

Why advisory lock and not ``filelock``:

  * Advisory locks live in the same shared resource we already need
    (Postgres).
  * They auto-release when the connection closes — a crashed worker
    can't strand the lock the way a filesystem lock can.
  * No filesystem assumptions; works the same on a hosted runner, a
    GHA service container, or a dev docker-compose.
"""
import os

import sqlalchemy as sa
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.base import Base


TEST_DATABASE_URL = os.environ["TEST_DATABASE_URL"]
TEMPLATE_DB_NAME = "myapp_test_template"

# Arbitrary 64-bit int; only needs to be unique within the cluster
# so no other code grabs the same lock.
_TEMPLATE_LOCK_ID = 7321456789012345


def _split_db_url(url: str) -> tuple[str, str] | None:
    """Return ``(prefix, dbname)`` or None if URL doesn't have a dbname."""
    if "/" not in url.split("@", 1)[-1]:
        return None
    prefix, dbname = url.rsplit("/", 1)
    if "?" in dbname:
        dbname, _, _ = dbname.partition("?")
    return prefix, dbname


async def _ensure_template_db(admin_url: str, template_url: str) -> None:
    """Create the template DB with schema pre-loaded if it doesn't
    exist yet. Idempotent: second call is a no-op when both the DB
    and the schema are already present."""
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

    # Load schema into the template if not already there. ``users``
    # is the sentinel — much cheaper than dropping and rebuilding
    # every run.
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
    """Drop the per-worker DB if it exists (terminating stale
    connections from a previous pytest run) and recreate it from
    the template. ``CREATE DATABASE ... TEMPLATE`` is a fast
    file-level copy, no SQL replay."""
    admin_engine = create_async_engine(
        admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool,
    )
    try:
        async with admin_engine.connect() as conn:
            # Kick any leftover connections so DROP doesn't block.
            await conn.execute(
                sa.text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :n AND pid <> pg_backend_pid()"
                ),
                {"n": dbname},
            )
            await conn.execute(
                sa.text(f'DROP DATABASE IF EXISTS "{dbname}"')
            )
            await conn.execute(
                sa.text(
                    f'CREATE DATABASE "{dbname}" '
                    f'TEMPLATE "{TEMPLATE_DB_NAME}"'
                )
            )
    finally:
        await admin_engine.dispose()


async def _setup_db_via_template() -> None:
    """Template-based setup used when running under pytest-xdist.

    Postgres advisory lock serialises the template creation across
    workers; first one in pays the create_all cost, others just
    clone."""
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
            # Blocks until acquired; auto-released when conn closes.
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

    # Clones can run concurrently across workers (no per-DB lock
    # contention) — postgres only briefly read-locks the template.
    await _clone_template_to(admin_url, dbname)
