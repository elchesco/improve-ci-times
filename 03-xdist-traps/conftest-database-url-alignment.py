"""Round 3 — Trap 3: ``DATABASE_URL`` divergence.

The test failed in CI with ``relation "subscriptions" does not exist``
even though the migrations ran.

Root cause: a background worker (``expire_comp_subscriptions``) does

    from app.db.session import AsyncSessionLocal

at module load. ``AsyncSessionLocal`` is bound to an engine built
from ``settings.DATABASE_URL`` (not ``TEST_DATABASE_URL``). Before
the per-worker suffix the two URLs happened to point at the same DB
in CI. With the suffix they diverged:

  * TestingSessionLocal  → myapp_test_gw0   (has tables)
  * AsyncSessionLocal    → myapp_test       (never schemaed)

The worker hit an empty DB and exploded.

Fix: align ``DATABASE_URL`` to ``TEST_DATABASE_URL`` BEFORE
``app.main`` imports. Once the engine is built with the right URL,
every ``from app.db.session import X`` in the app picks up the
correct binding.

An earlier attempt monkey-patched ``app.db.session.AsyncSessionLocal``
after the fact. That was a no-op: modules that had already done
``from app.db.session import AsyncSessionLocal`` had captured the
original binding. Patching the module attribute doesn't update the
imported names.
"""

import os


_test_db = os.environ.get("TEST_DATABASE_URL")
if _test_db:
    # Settings.DATABASE_URL normalises ``postgresql://`` →
    # ``postgresql+asyncpg://`` anyway, but be explicit.
    os.environ["DATABASE_URL"] = _test_db

# (then the per-worker suffix block — round 3, file 1)
# (then the regular ``from app.main import app`` etc.)
