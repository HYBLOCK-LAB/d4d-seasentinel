from __future__ import annotations

import os
import uuid
from datetime import datetime

import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from mda.paths import lake_dir


def _partition(ts: datetime) -> tuple[str, str]:
    return ts.strftime("%Y-%m-%d"), ts.strftime("%H")


def write_batch(dataset: str, rows: list[dict], ts_field: str = "ts") -> int:
    if not rows:
        return 0
    buckets: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        ts = row[ts_field]
        buckets.setdefault(_partition(ts), []).append(row)
    written = 0
    for (day, hour), bucket in buckets.items():
        target = lake_dir(dataset, f"date={day}", f"hour={hour}")
        target.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pylist(bucket)
        path = target / f"{uuid.uuid4().hex}.parquet"
        tmp = path.with_suffix(".parquet.tmp")
        pq.write_table(table, tmp)
        os.replace(tmp, path)
        written += len(bucket)
    return written


def read_dataset(dataset: str) -> pa.Table:
    root = lake_dir(dataset)
    if not root.exists():
        return pa.table({})
    return ds.dataset(root, format="parquet", partitioning="hive").to_table()
