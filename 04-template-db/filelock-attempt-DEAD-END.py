"""DEAD END — do not use.
============================

First attempt at serialising template creation across xdist workers
used python-filelock + asyncio.to_thread.

Workers hung at the 120s timeout for reasons I couldn't pin down
quickly:

  * Direct calls to ``_setup_db_via_template`` worked.
  * Single-test smokes worked.
  * Anything that ran multiple tests across workers hit the timeout.

Switched to a Postgres advisory lock (see ``conftest-template-db.py``)
which:

  * Lives in the shared resource we already need (Postgres).
  * Auto-releases on connection close — a crashed worker can't
    strand the lock.
  * Has no filesystem assumptions.

Keeping this file around as documentation of the dead end so the
next person doesn't relitigate the choice.
"""

import asyncio
import filelock  # noqa: F401  — would be a runtime dep


# DO NOT USE
async def _setup_db_via_template_DO_NOT_USE() -> None:
    _TEMPLATE_LOCK_PATH = "/tmp/myapp_test_template.lock"

    lock = filelock.FileLock(_TEMPLATE_LOCK_PATH, timeout=120)
    await asyncio.to_thread(lock.acquire)
    try:
        # … template create + clone …
        pass
    finally:
        lock.release()
