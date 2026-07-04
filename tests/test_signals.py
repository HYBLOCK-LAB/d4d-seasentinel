from __future__ import annotations

from datetime import date

from mda.config import Aoi, Event, load_index_config
from mda.pipelines.signals import _collection_tasks


def _events():
    return {
        "whitsun_reef": Event("whitsun_2021", "w", date(2021, 3, 7), "whitsun_reef", 45, 7),
        "sabina_shoal": Event("sabina_2024", "s", date(2024, 8, 31), "sabina_shoal", 45, 7),
    }


def test_staging_aoi_gets_task_per_target_window():
    cfg = load_index_config()
    hainan = Aoi("hainan_staging", "Hainan", "staging", [109.3, 18.0, 111.0, 19.6], staging_for=["whitsun_reef", "sabina_shoal"])
    whitsun = Aoi("whitsun_reef", "Whitsun", "reef", [114.5, 9.83, 114.8, 10.13])
    tasks = _collection_tasks([hainan, whitsun], _events(), cfg, date(2020, 1, 1), date(2025, 1, 1), True)

    staging_tasks = [t for t in tasks if t[0].aoi_id == "hainan_staging"]
    targets = {t[3] for t in staging_tasks}
    assert targets == {"whitsun_reef", "sabina_shoal"}
    # each staging task window centers on its target event, disjoint (2021 vs 2024)
    windows = {t[3]: (t[1], t[2]) for t in staging_tasks}
    assert windows["whitsun_reef"][1].year == 2021
    assert windows["sabina_shoal"][1].year == 2024


def test_reef_with_event_gets_single_untargeted_task():
    cfg = load_index_config()
    whitsun = Aoi("whitsun_reef", "Whitsun", "reef", [114.5, 9.83, 114.8, 10.13])
    tasks = _collection_tasks([whitsun], _events(), cfg, date(2020, 1, 1), date(2025, 1, 1), True)
    assert len(tasks) == 1
    assert tasks[0][3] is None


def test_full_range_mode_ignores_events():
    cfg = load_index_config()
    whitsun = Aoi("whitsun_reef", "Whitsun", "reef", [114.5, 9.83, 114.8, 10.13])
    tasks = _collection_tasks([whitsun], _events(), cfg, date(2022, 1, 1), date(2022, 6, 1), False)
    assert tasks == [(whitsun, date(2022, 1, 1), date(2022, 6, 1), None)]
