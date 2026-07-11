"""Regression checks for the review fixes on the money/data path. Isolated temp
DB, no network. Run: python -m tests.test_cache_db"""
import os
import tempfile

_DB = os.path.join(tempfile.gettempdir(), "openprop_cachedb.db")
os.environ["DB_PATH"] = _DB
# start from a clean DB so the cache/spend assertions are order-independent
for _ext in ("", "-wal", "-shm"):
    try:
        os.remove(_DB + _ext)
    except FileNotFoundError:
        pass

from app.cache import cached, spend_this_month  # noqa: E402
from app.db import init_db, save_property       # noqa: E402
from app.flags import owner_key                  # noqa: E402

init_db()  # pytest runs the tests without __main__ below, and they need the schema


def test_cache_none_is_a_hit_and_not_double_billed():
    # a paid fetch that returns None must be cached as a real hit — not re-fetched
    # (which would re-bill). Exercises the _MISS sentinel + spend accounting.
    calls = []
    def fetch():
        calls.append(1)
        return None
    r1 = cached("t", "e", {"a": 1}, fetch, cost_cents=5)
    r2 = cached("t", "e", {"a": 1}, fetch, cost_cents=5)
    assert r1 is None and r2 is None
    assert len(calls) == 1, f"fetched twice — None not treated as a hit ({len(calls)})"
    assert spend_this_month() == 5, spend_this_month()  # billed exactly once
    print("cache: None cached as hit, billed once OK")


def test_save_property_dedupes_null_zip():
    a = save_property({"address": "1 Main St", "zip": None, "source": "x"})
    b = save_property({"address": "1 Main St", "zip": None, "source": "x"})
    assert a == b, f"NULL-zip lookup duplicated the row ({a} != {b})"
    print("db: NULL-zip upsert dedupes OK")


def test_owner_key_requires_mailing():
    assert owner_key("John Smith", None) is None        # name alone must not group
    assert owner_key("John Smith", "500 Park Ave") is not None
    print("flags: owner_key requires mailing OK")


if __name__ == "__main__":
    init_db()
    test_cache_none_is_a_hit_and_not_double_billed()
    test_save_property_dedupes_null_zip()
    test_owner_key_requires_mailing()
    print("cache_db test OK")
