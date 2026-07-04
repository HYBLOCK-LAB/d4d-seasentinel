from __future__ import annotations

import argparse
from datetime import date

from presail.config import load_aois
from presail.gdelt import fetch_volraw_and_tone
from presail.gfw import fetch_4wings_daily, token


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

    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
