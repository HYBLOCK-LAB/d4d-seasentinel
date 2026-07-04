from __future__ import annotations

import argparse

from mda.store import migrate_legacy, pg


def _cmd_init_db(args: argparse.Namespace) -> None:
    with pg.connect() as conn:
        pg.ensure_schema(conn)
    print("schema applied")


def _cmd_migrate(args: argparse.Namespace) -> None:
    counts = migrate_legacy.migrate()
    for table, n in counts.items():
        print(f"  {table}: {n}")
    report = migrate_legacy.verify()
    print("verify:")
    all_ok = True
    for table, r in report.items():
        flag = "ok" if r["ok"] else "MISMATCH"
        all_ok = all_ok and r["ok"]
        print(f"  {table}: expected={r['expected']} db={r['db']} {flag}")
    if not all_ok:
        raise SystemExit("migration parity check failed")


def _cmd_migrate_verify(args: argparse.Namespace) -> None:
    report = migrate_legacy.verify()
    all_ok = True
    for table, r in report.items():
        flag = "ok" if r["ok"] else "MISMATCH"
        all_ok = all_ok and r["ok"]
        print(f"  {table}: expected={r['expected']} db={r['db']} {flag}")
    if not all_ok:
        raise SystemExit("parity check failed")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mda")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db").set_defaults(func=_cmd_init_db)
    sub.add_parser("migrate").set_defaults(func=_cmd_migrate)
    sub.add_parser("migrate-verify").set_defaults(func=_cmd_migrate_verify)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
