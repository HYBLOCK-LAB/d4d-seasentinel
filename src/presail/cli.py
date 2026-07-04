from __future__ import annotations

import argparse
from datetime import date

import json

import pandas as pd

from presail.artifact import build_artifact
from presail.backtest import run_backtest
from presail.charts import render_event_charts
from presail.config import load_aois, load_events, load_index_config
from presail.gdelt import fetch_volraw_and_tone
from presail.gfw import fetch_4wings_daily, token
from presail.index import compute_index
from presail.paths import data_dir
from presail.signals import build_signals


def _date(text: str) -> date:
    return date.fromisoformat(text)


def _aoi(aoi_id: str):
    for aoi in load_aois():
        if aoi.aoi_id == aoi_id:
            return aoi
    raise SystemExit(f"unknown aoi: {aoi_id}")


def _cmd_fetch_gdelt(args: argparse.Namespace) -> None:
    rows = fetch_volraw_and_tone(args.query, args.start, args.end)
    nonzero = [r for r in rows if r["article_count"] > 0]
    print(f"query={args.query!r} rows={len(rows)} nonzero_days={len(nonzero)}")
    for row in nonzero[:5]:
        print(f"  {row['date']} count={row['article_count']:.0f} volume={row['monitored_volume']:.0f}")


def _cmd_fetch_gfw(args: argparse.Namespace) -> None:
    if not token():
        print("GFW_TOKEN not set; skipping GFW (GDELT-only mode).")
        return
    aoi = _aoi(args.aoi)
    rows = fetch_4wings_daily(args.dataset, aoi.aoi_id, aoi.bbox, args.start, args.end)
    nonzero = [r for r in rows if r["value"] > 0]
    print(f"dataset={args.dataset} aoi={aoi.aoi_id} days={len(rows)} nonzero={len(nonzero)}")
    for row in rows[:8]:
        print(f"  {row['date']} value={row['value']:.1f}")


def _cmd_build_index(args: argparse.Namespace) -> None:
    signals = build_signals(args.start, args.end, gdelt_only=args.gdelt_only)
    index_df, contrib_df = compute_index(signals, load_index_config())
    index_path = data_dir("processed", "index.parquet")
    contrib_path = data_dir("processed", "contributions.parquet")
    index_df.to_parquet(index_path, index=False)
    contrib_df.to_parquet(contrib_path, index=False)
    alerts = index_df[index_df["level"] != "NONE"]
    print(f"index rows={len(index_df)} aois={index_df['aoi_id'].nunique()} alert/watch days={len(alerts)}")
    print(f"wrote {index_path}")


def _cmd_backtest(args: argparse.Namespace) -> None:
    index_df = pd.read_parquet(data_dir("processed", "index.parquet"))
    contrib_df = pd.read_parquet(data_dir("processed", "contributions.parquet"))
    cfg = load_index_config()
    events = load_events()
    results = run_backtest(index_df, events, cfg)
    print(f"{'event':<18}{'lead_days':>10}{'peak':>8}{'pctile':>8}{'false_pos':>10}")
    for r in results:
        print(
            f"{r['event_id']:<18}{str(r.get('lead_time_days')):>10}{r.get('peak_index', ''):>8}"
            f"{r.get('peak_percentile', ''):>8}{r.get('false_positive_episodes', ''):>10}"
        )
    for event in events:
        render_event_charts(index_df, contrib_df, event, cfg)
    print("charts written to charts/")


def _cmd_run(args: argparse.Namespace) -> None:
    cfg = load_index_config()
    events = load_events()
    aois = load_aois()

    signals = build_signals(args.start, args.end, gdelt_only=args.gdelt_only)
    index_df, contrib_df = compute_index(signals, cfg)
    index_df.to_parquet(data_dir("processed", "index.parquet"), index=False)
    contrib_df.to_parquet(data_dir("processed", "contributions.parquet"), index=False)

    backtests = run_backtest(index_df, events, cfg)
    by_event = {b["event_id"]: b for b in backtests}
    for event in events:
        charts = render_event_charts(index_df, contrib_df, event, cfg)
        by_event.get(event.event_id, {}).update(charts)

    artifact = build_artifact(index_df, contrib_df, aois, events, backtests, cfg)
    artifact_path = data_dir("artifacts", "latest.json")
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2))
    print(f"wrote {artifact_path} (aois={len(artifact['aois'])}, events={len(backtests)})")
    for b in backtests:
        print(f"  {b['event_id']}: lead={b.get('lead_time_days')} peak={b.get('peak_index')}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="presail")
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("fetch-gdelt")
    g.add_argument("--query", required=True)
    g.add_argument("--start", type=_date, required=True)
    g.add_argument("--end", type=_date, required=True)
    g.set_defaults(func=_cmd_fetch_gdelt)

    f = sub.add_parser("fetch-gfw")
    f.add_argument("--dataset", default="public-global-presence:latest")
    f.add_argument("--aoi", required=True)
    f.add_argument("--start", type=_date, required=True)
    f.add_argument("--end", type=_date, required=True)
    f.set_defaults(func=_cmd_fetch_gfw)

    b = sub.add_parser("build-index")
    b.add_argument("--start", type=_date, required=True)
    b.add_argument("--end", type=_date, required=True)
    b.add_argument("--gdelt-only", action="store_true")
    b.set_defaults(func=_cmd_build_index)

    bt = sub.add_parser("backtest")
    bt.set_defaults(func=_cmd_backtest)

    r = sub.add_parser("run")
    r.add_argument("--start", type=_date, required=True)
    r.add_argument("--end", type=_date, required=True)
    r.add_argument("--gdelt-only", action="store_true")
    r.set_defaults(func=_cmd_run)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
