"""Command-line entry point."""

from __future__ import annotations

import argparse
import logging
import sys

from .config import platform_keys

log = logging.getLogger("bridge")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("httpx", "httpcore", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def cmd_init_db(args: argparse.Namespace) -> int:
    from .db.session import init_db

    init_db(drop=args.drop)
    print("Database initialised." + (" (dropped existing tables)" if args.drop else ""))
    return 0


def _ensure_fixtures(variants: int = 9) -> None:
    """Generate the fixture corpus if it is not already on disk."""
    import importlib.util

    from .config import PROJECT_ROOT

    fixture_root = PROJECT_ROOT / "tests" / "fixtures"
    needed = "homepage.html" if variants <= 1 else f"homepage.v{variants - 1}.html"
    missing = [
        key for key in platform_keys()
        if not (fixture_root / key / "index.json").exists()
        or not (fixture_root / key / needed).exists()
    ]
    if not missing:
        return

    generator = fixture_root / "generate.py"
    if not generator.exists():
        raise SystemExit(
            f"Fixtures are missing for {', '.join(missing)} and the generator "
            f"({generator}) is absent. Cannot build a fixture-mode history."
        )

    print(f"Fixtures incomplete for {', '.join(missing)} — generating "
          f"{variants} variants (one-time, a few seconds)...")
    spec = importlib.util.spec_from_file_location("_bridge_fixture_generate", generator)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.generate(variants)
    print()


def _run_collectors(platforms: list[str], module: str, mode: str,
                    variant: str | None, max_pages: int | None) -> list[dict]:
    from .collect.banners import BannerCollector
    from .collect.retail import COLLECTORS
    from .collect.search import SearchCollector

    results: list[dict] = []
    for platform in platforms:
        if module in ("listing", "all"):
            collector = COLLECTORS[platform](
                mode=mode, variant=variant, max_pages=max_pages
            )
            results.append(collector.run())
        if module in ("banner", "all"):
            results.append(BannerCollector(platform, mode=mode, variant=variant).run())
        if module in ("search", "all"):
            results.append(SearchCollector(platform, mode=mode, variant=variant).run())
    return results


def cmd_collect(args: argparse.Namespace) -> int:
    platforms = args.platform or list(platform_keys())
    if args.mode != "live":
        _ensure_fixtures()
    results = _run_collectors(platforms, args.module, args.mode, args.variant, args.max_pages)

    print(f"\n{'=' * 70}")
    for row in results:
        summary = ", ".join(f"{k}={v}" for k, v in row.items() if k not in ("platform",))
        print(f"  {row['platform']:<20} {summary}")
    print("=" * 70)

    if args.metrics:
        return cmd_metrics(args)
    return 0


def build_history(runs: int = 9, platforms: list[str] | None = None,
                  max_pages: int | None = None, quiet: bool = False) -> int:
    """Replay N fixture variants as successive collection runs."""
    from .metrics.alerts import generate_alerts

    def say(message: str) -> None:
        if not quiet:
            print(message)

    _ensure_fixtures(runs)
    platforms = platforms or list(platform_keys())
    total = 0
    for index in range(runs):
        variant = None if index == 0 else f"v{index}"
        say(f"\n--- run {index + 1}/{runs} (variant={variant or 'base'}) ---")
        results = _run_collectors(platforms, "all", "fixture", variant, max_pages)
        for row in results:
            total += row.get("items_parsed", 0) or row.get("results_parsed", 0) or 0
        if index > 0:
            created = generate_alerts()
            say(f"    alerts generated: {created}")
    return total


def cmd_build_history(args: argparse.Namespace) -> int:
    total = build_history(runs=args.runs, platforms=args.platform,
                          max_pages=args.max_pages)

    print(f"\nHistory built: {args.runs} runs, {total} observations parsed.")
    if total == 0:
        print(
            "\nERROR: no observations were parsed. The exports and dashboard "
            "would be empty.\n"
            "       Check that tests/fixtures/<platform>/index.json exists and "
            "that selectors\n       in config/platforms.yaml still match the "
            "fixture markup.",
            file=sys.stderr,
        )
        return 1
    return 0


def cmd_metrics(args: argparse.Namespace) -> int:
    from .metrics.alerts import generate_alerts

    created = generate_alerts()
    print(f"Alerts generated: {created}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    from .export.writer import export_all

    paths = export_all(fmt=args.format, output_dir=args.output)
    print(f"\nWrote {len(paths)} file(s):")
    for path in paths:
        print(f"  {path}")
    return 0


def cmd_schedule(args: argparse.Namespace) -> int:
    from .schedule.runner import run_scheduler

    run_scheduler(mode=args.mode, once=args.once)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    from sqlalchemy import func, select

    from .db.models import Alert, Observation, Product, Run
    from .db.session import session_scope

    with session_scope() as session:
        runs = session.execute(
            select(Run.platform, Run.run_type, Run.status, func.count(Run.id))
            .group_by(Run.platform, Run.run_type, Run.status)
        ).all()
        products = session.execute(
            select(Product.platform, Product.brand, func.count(Product.id))
            .group_by(Product.platform, Product.brand)
        ).all()
        obs_count = session.execute(select(func.count(Observation.id))).scalar_one()
        alert_count = session.execute(select(func.count(Alert.id))).scalar_one()
        window = session.execute(
            select(func.min(Observation.observed_at), func.max(Observation.observed_at))
        ).one()

    print("\nRUNS")
    for platform, run_type, status, count in runs:
        print(f"  {platform:<20} {run_type:<9} {status:<8} {count}")
    print("\nPRODUCTS BY BRAND")
    for platform, brand, count in products:
        print(f"  {platform:<20} {brand:<10} {count}")
    print(f"\nObservations : {obs_count:,}")
    print(f"Alerts       : {alert_count:,}")
    print(f"Window       : {window[0]} -> {window[1]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bridge",
        description="Retail price, promotion & brand positioning benchmark.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init-db", help="create database tables")
    p_init.add_argument("--drop", action="store_true", help="drop existing tables first")
    p_init.set_defaults(func=cmd_init_db)

    p_collect = sub.add_parser("collect", help="run one collection pass")
    p_collect.add_argument("--platform", action="append", choices=list(platform_keys()))
    p_collect.add_argument("--module", default="all",
                           choices=["all", "listing", "banner", "search"])
    p_collect.add_argument("--mode", default="auto", choices=["auto", "fixture", "live"])
    p_collect.add_argument("--variant", default=None,
                           help="fixture variant, e.g. v3")
    p_collect.add_argument("--max-pages", type=int, default=None)
    p_collect.add_argument("--metrics", action="store_true",
                           help="generate alerts after collecting")
    p_collect.set_defaults(func=cmd_collect)

    p_hist = sub.add_parser("build-history",
                            help="replay fixture variants as successive runs")
    p_hist.add_argument("--runs", type=int, default=9)
    p_hist.add_argument("--platform", action="append", choices=list(platform_keys()))
    p_hist.add_argument("--max-pages", type=int, default=None)
    p_hist.set_defaults(func=cmd_build_history)

    p_metrics = sub.add_parser("metrics", help="recompute alerts")
    p_metrics.set_defaults(func=cmd_metrics)

    p_export = sub.add_parser("export", help="write PSV / Excel deliverables")
    p_export.add_argument("--format", default="both", choices=["psv", "excel", "both"])
    p_export.add_argument("--output", default=None)
    p_export.set_defaults(func=cmd_export)

    p_sched = sub.add_parser("schedule", help="run the 3x-daily scheduler")
    p_sched.add_argument("--mode", default="auto", choices=["auto", "fixture", "live"])
    p_sched.add_argument("--once", action="store_true",
                         help="execute one slot immediately and exit")
    p_sched.set_defaults(func=cmd_schedule)

    p_status = sub.add_parser("status", help="summarise warehouse contents")
    p_status.set_defaults(func=cmd_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
