#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== Pre-Sail Index demo =="
echo "Building index and backtesting 2021/2024 gray-zone events..."
uv run python -m presail.cli run --start 2020-08-01 --end 2024-12-31

echo
echo "== Backtest summary =="
uv run python - <<'PY'
import json
from presail.paths import data_dir
art = json.loads((data_dir("artifacts", "latest.json")).read_text())
for b in art["backtests"]:
    print(f"  {b['event_id']:<18} lead={b.get('lead_time_days')} days  "
          f"peak={b.get('peak_index')}  pctile={b.get('peak_percentile')}  "
          f"false_pos={b.get('false_positive_episodes')}")
print("\nArtifact: data/artifacts/latest.json")
print("Charts:")
for b in art["backtests"]:
    if b.get("chart_timeline"):
        print("  " + b["chart_timeline"])
PY
