"""Round 3 — Trap 1: ``DROP SCHEMA`` across workers.

Each pytest-xdist worker is its own process running its own
session. ``setup_db`` is scope="session" autouse, so it runs in
every worker. With workers pointed at the SAME database they take
turns dropping each other's schemas mid-test.

Fix: one database per worker, suffix the dbname with
``PYTEST_XDIST_WORKER`` (``gw0``, ``gw1``, ...). Worker gw0 gets
``myapp_test_gw0``, gw1 gets ``_gw1``, and so on.
"""
import os


def _suffix_dburl(url: str, worker: str) -> str:
    """Insert ``_<worker>`` before any query string, preserving the
    rest of the URL (port, query, scheme)."""
    if "?" in url:
        url_part, _, query = url.partition("?")
        query = f"?{query}"
    else:
        url_part, query = url, ""
    if "/" not in url_part.split("@", 1)[-1]:
        return url
    prefix, dbname = url_part.rsplit("/", 1)
    return f"{prefix}/{dbname}_{worker}{query}"


_XDIST_WORKER = os.environ.get("PYTEST_XDIST_WORKER")
if _XDIST_WORKER:
    for key in ("DATABASE_URL", "TEST_DATABASE_URL"):
        if val := os.environ.get(key):
            os.environ[key] = _suffix_dburl(val, _XDIST_WORKER)
