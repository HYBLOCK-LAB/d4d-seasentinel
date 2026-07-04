from __future__ import annotations

import json

import pytest

from mda.store.cache import cache_key, get_or_fetch


def test_get_or_fetch_writes_then_reads(tmp_path):
    path = tmp_path / "sub" / "value.json"
    calls = []

    def fetch():
        calls.append(1)
        return {"n": 7}

    assert get_or_fetch(path, fetch) == {"n": 7}
    assert get_or_fetch(path, fetch) == {"n": 7}
    assert len(calls) == 1


def test_fetch_exception_writes_nothing(tmp_path):
    path = tmp_path / "value.json"

    def boom():
        raise RuntimeError("network down")

    with pytest.raises(RuntimeError):
        get_or_fetch(path, boom)

    assert not path.exists()
    assert not (path.with_name(path.name + ".tmp")).exists()


def test_existing_cache_is_never_refetched(tmp_path):
    path = tmp_path / "value.json"
    path.write_text(json.dumps({"good": True}))

    def boom():
        raise RuntimeError("should not be called")

    assert get_or_fetch(path, boom) == {"good": True}


def test_cache_key_is_stable_and_short():
    assert cache_key("a", "b") == cache_key("a", "b")
    assert cache_key("a", "b") != cache_key("a", "c")
    assert len(cache_key("a")) == 16
