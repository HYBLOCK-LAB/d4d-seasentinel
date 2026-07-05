from __future__ import annotations

import argparse
import json
import logging
from datetime import date

from mda.config import load_aois, load_events, load_index_config
from mda.paths import data_dir
from mda.store import pg


def _date(text: str) -> date:
    return date.fromisoformat(text)


def _aoi(aoi_id: str):
    for aoi in load_aois():
        if aoi.aoi_id == aoi_id:
            return aoi
    raise SystemExit(f"unknown aoi: {aoi_id}")


def _print_verify(report: dict) -> None:
    all_ok = True
    for table, r in report.items():
        flag = "ok" if r["ok"] else "MISMATCH"
        all_ok = all_ok and r["ok"]
        print(f"  {table}: expected={r['expected']} db={r['db']} {flag}")
    if not all_ok:
        raise SystemExit("parity check failed")


def _cmd_init_db(args) -> None:
    with pg.connect() as conn:
        pg.ensure_schema(conn)
    print("schema applied")


def _cmd_migrate(args) -> None:
    from mda.store import migrate_legacy

    for table, n in migrate_legacy.migrate().items():
        print(f"  {table}: {n}")
    print("verify:")
    _print_verify(migrate_legacy.verify())


def _cmd_migrate_verify(args) -> None:
    from mda.store import migrate_legacy

    _print_verify(migrate_legacy.verify())


def _cmd_fetch_gdelt(args) -> None:
    from mda.collectors.gdelt import fetch_volraw_and_tone

    rows = fetch_volraw_and_tone(args.query, args.start, args.end)
    nonzero = [r for r in rows if r["article_count"] > 0]
    print(f"query={args.query!r} rows={len(rows)} nonzero_days={len(nonzero)}")


def _cmd_fetch_gfw(args) -> None:
    from mda.collectors.gfw import fetch_4wings_daily, token

    if not token():
        print("GFW_TOKEN not set; skipping GFW.")
        return
    aoi = _aoi(args.aoi)
    rows = fetch_4wings_daily(args.dataset, aoi.aoi_id, aoi.bbox, args.start, args.end)
    nonzero = [r for r in rows if r["value"] > 0]
    print(f"dataset={args.dataset} aoi={aoi.aoi_id} days={len(rows)} nonzero={len(nonzero)}")


def _cmd_build_index(args) -> None:
    from mda.pipelines import persist
    from mda.pipelines.index import compute_index
    from mda.pipelines.signals import build_signals

    signals = build_signals(args.start, args.end, gdelt_only=args.gdelt_only, event_windows=not args.full_range)
    index_df, contrib_df = compute_index(signals, load_index_config())
    index_df.to_parquet(data_dir("processed", "index.parquet"), index=False)
    contrib_df.to_parquet(data_dir("processed", "contributions.parquet"), index=False)
    alerts = index_df[index_df["level"] != "NONE"]
    print(f"index rows={len(index_df)} aois={index_df['aoi_id'].nunique()} alert/watch days={len(alerts)}")
    if not args.no_persist:
        print("persisted:", persist.persist_run(signals, index_df, contrib_df))


def _cmd_collect_weather(args) -> None:
    from mda.collectors import weather_openmeteo

    print(weather_openmeteo.collect(args.start, args.end))


def _cmd_collect_stealthmole(args) -> None:
    from mda.collectors import stealthmole

    print(stealthmole.collect(max_items=args.max_items))


def _cmd_collect_reference(args) -> None:
    from mda.collectors import reference

    print(reference.collect_all())


def _cmd_collect_gfw_events(args) -> None:
    from mda.collectors import gfw_events

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    regions = [r.strip() for r in args.regions.split(",") if r.strip()]
    kwargs = {"limit": args.limit} if args.limit else {}
    print(gfw_events.collect(args.start, args.end, regions, **kwargs))


def _cmd_retention(args) -> None:
    from mda.store import retention

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    print(retention.run_retention(keep_days=args.keep_days, batch_size=args.batch_size, max_days=args.max_days))


def _cmd_analyze(args) -> None:
    from mda.pipelines import scoring

    print(scoring.run_scoring(min_gap_hours=args.min_gap_hours, cable_km=args.cable_km))


def _cmd_foundry_sync(args) -> None:
    from mda.sync import sync

    print(sync.sync_bounded())


def _cmd_lake_sync(args) -> None:
    from mda.store import s3

    print(s3.sync_lake())


def _cmd_export_dashboard(args) -> None:
    from datetime import datetime, timedelta, timezone

    from mda.pipelines import exporter

    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=args.hours)
    print(exporter.export_dashboard(args.region, start, end))


def _cmd_ais_stream(args) -> None:
    from mda.collectors import aisstream_realtime

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    regions = [r.strip() for r in args.regions.split(",") if r.strip()]
    stats = aisstream_realtime.run_sync(regions, duration=args.duration, to_lake=args.to_lake)
    print(f"ais-stream regions={regions} {stats}")


def _cmd_backtest(args) -> None:
    import pandas as pd

    from mda.pipelines.backtest import run_backtest
    from mda.pipelines.charts import render_event_charts

    index_df = pd.read_parquet(data_dir("processed", "index.parquet"))
    contrib_df = pd.read_parquet(data_dir("processed", "contributions.parquet"))
    cfg = load_index_config()
    events = load_events()
    results = run_backtest(index_df, events, cfg)
    print(f"{'event':<18}{'lead':>8}{'peak':>8}{'pctile':>8}{'fp':>6}")
    for r in results:
        print(
            f"{r['event_id']:<18}{str(r.get('lead_time_days')):>8}{r.get('peak_index', ''):>8}"
            f"{r.get('peak_percentile', ''):>8}{r.get('false_positive_episodes', ''):>6}"
        )
    for event in events:
        render_event_charts(index_df, contrib_df, event, cfg)


def _cmd_run(args) -> None:
    from mda.pipelines import persist
    from mda.pipelines.artifact import build_artifact
    from mda.pipelines.backtest import run_backtest
    from mda.pipelines.charts import render_event_charts
    from mda.pipelines.index import compute_index
    from mda.pipelines.signals import build_signals

    cfg = load_index_config()
    events = load_events()
    aois = load_aois()
    signals = build_signals(args.start, args.end, gdelt_only=args.gdelt_only, event_windows=not args.full_range)
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
    if not args.no_persist:
        print("persisted:", persist.persist_run(signals, index_df, contrib_df))
        persist.persist_backtests(backtests)
    for b in backtests:
        print(f"  {b['event_id']}: lead={b.get('lead_time_days')} peak={b.get('peak_index')}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mda")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db").set_defaults(func=_cmd_init_db)
    sub.add_parser("migrate").set_defaults(func=_cmd_migrate)
    sub.add_parser("migrate-verify").set_defaults(func=_cmd_migrate_verify)

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

    for name, func in (("build-index", _cmd_build_index), ("run", _cmd_run)):
        p = sub.add_parser(name)
        p.add_argument("--start", type=_date, required=True)
        p.add_argument("--end", type=_date, required=True)
        p.add_argument("--gdelt-only", action="store_true")
        p.add_argument("--full-range", action="store_true")
        p.add_argument("--no-persist", action="store_true")
        p.set_defaults(func=func)

    sub.add_parser("backtest").set_defaults(func=_cmd_backtest)

    a = sub.add_parser("ais-stream")
    a.add_argument("--regions", default="west_sea")
    a.add_argument("--duration", type=float, default=None)
    a.add_argument("--to-lake", action="store_true")
    a.set_defaults(func=_cmd_ais_stream)

    ge = sub.add_parser("collect-gfw-events")
    ge.add_argument("--start", type=_date, required=True)
    ge.add_argument("--end", type=_date, required=True)
    ge.add_argument("--regions", default="west_sea")
    ge.add_argument("--limit", type=int, default=None, help=argparse.SUPPRESS)
    ge.set_defaults(func=_cmd_collect_gfw_events)

    rt = sub.add_parser("retention")
    rt.add_argument("--keep-days", type=int, default=14)
    rt.add_argument("--batch-size", type=int, default=50_000)
    rt.add_argument("--max-days", type=int, default=None)
    rt.set_defaults(func=_cmd_retention)

    w = sub.add_parser("collect-weather")
    w.add_argument("--start", type=_date, required=True)
    w.add_argument("--end", type=_date, required=True)
    w.set_defaults(func=_cmd_collect_weather)

    sm = sub.add_parser("collect-stealthmole")
    sm.add_argument("--max-items", type=int, default=None)
    sm.set_defaults(func=_cmd_collect_stealthmole)

    sub.add_parser("collect-reference").set_defaults(func=_cmd_collect_reference)

    an = sub.add_parser("analyze")
    an.add_argument("--min-gap-hours", type=float, default=6.0)
    an.add_argument("--cable-km", type=float, default=3.0)
    an.set_defaults(func=_cmd_analyze)

    ed = sub.add_parser("export-dashboard")
    ed.add_argument("--region", default="west_sea")
    ed.add_argument("--hours", type=float, default=72.0)
    ed.set_defaults(func=_cmd_export_dashboard)

    sub.add_parser("foundry-sync").set_defaults(func=_cmd_foundry_sync)
    sub.add_parser("lake-sync").set_defaults(func=_cmd_lake_sync)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
