from __future__ import annotations

from datetime import datetime, timezone

from mda.store.retention import bucket_10min


def test_bucket_10min_floors_to_utc_bucket():
    ts = datetime(2026, 6, 25, 3, 19, 59, tzinfo=timezone.utc)
    assert bucket_10min(ts) == datetime(2026, 6, 25, 3, 10, tzinfo=timezone.utc)


def test_bucket_10min_treats_naive_as_utc():
    ts = datetime(2026, 6, 25, 3, 20, 1)
    assert bucket_10min(ts) == datetime(2026, 6, 25, 3, 20, tzinfo=timezone.utc)
