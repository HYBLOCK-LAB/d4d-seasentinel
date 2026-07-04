from __future__ import annotations

import argparse
from datetime import date

from presail.gdelt import fetch_volraw_and_tone


def _date(text: str) -> date:
    return date.fromisoformat(text)


def _cmd_fetch_gdelt(args: argparse.Namespace) -> None:
    rows = fetch_volraw_and_tone(args.query, args.start, args.end)
    nonzero = [r for r in rows if r["article_count"] > 0]
    print(f"query={args.query!r} rows={len(rows)} nonzero_days={len(nonzero)}")
    for row in nonzero[:5]:
        print(f"  {row['date']} count={row['article_count']:.0f} volume={row['monitored_volume']:.0f}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="presail")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("fetch-gdelt")
    p.add_argument("--query", required=True)
    p.add_argument("--start", type=_date, required=True)
    p.add_argument("--end", type=_date, required=True)
    p.set_defaults(func=_cmd_fetch_gdelt)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
