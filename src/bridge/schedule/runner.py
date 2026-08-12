"""Scheduler implementing the brief's collection cadence.

    Multiple times/day : price & promotion updates, retailer audits, banner tracking
    Monthly            : brand benchmark scores (Share of Shelf), screenshots

Three fixed slots rather than "every 8 hours" so that runs land at comparable
times each day — comparing today's 09:00 to yesterday's 09:00 is meaningful in
a way that comparing arbitrary 8-hour offsets is not. Retail pricing is diurnal;
a drifting schedule would show phantom price movement.

Banner tracking runs once daily per the brief, on the morning slot.
"""

from __future__ import annotations

import logging
import signal
import sys
from datetime import datetime, timezone

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from ..config import platform_keys

log = logging.getLogger(__name__)

# UTC hours for the three daily slots.
SLOT_HOURS = {"morning": 6, "midday": 13, "evening": 20}


def run_slot(slot: str, mode: str = "auto") -> dict:
    """Execute one collection slot across all platforms."""
    from ..collect.banners import BannerCollector
    from ..collect.retail import COLLECTORS
    from ..collect.search import SearchCollector
    from ..metrics.alerts import generate_alerts

    started = datetime.now(timezone.utc)
    log.info("=== slot '%s' starting at %s ===", slot, started.isoformat(timespec="seconds"))

    summary: dict = {"slot": slot, "started_at": started.isoformat(), "results": []}

    for platform in platform_keys():
        try:
            # Modules 1, 2, 4, 5, 6 — every slot.
            summary["results"].append(COLLECTORS[platform](mode=mode).run())
        except Exception:
            log.exception("[%s] listing collection failed", platform)

        try:
            # Module 8 — every slot; search rankings move intraday.
            summary["results"].append(SearchCollector(platform, mode=mode).run())
        except Exception:
            log.exception("[%s] search collection failed", platform)

        # Module 3 — daily, per the brief. Running it three times would triple
        # the row count without adding signal: homepage banners are scheduled
        # merchandising, not intraday pricing.
        if slot == "morning":
            try:
                summary["results"].append(BannerCollector(platform, mode=mode).run())
            except Exception:
                log.exception("[%s] banner collection failed", platform)

    try:
        summary["alerts_created"] = generate_alerts()
    except Exception:
        log.exception("alert generation failed")
        summary["alerts_created"] = 0

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    summary["elapsed_seconds"] = round(elapsed, 1)
    log.info("=== slot '%s' finished in %.1fs, %d alerts ===",
             slot, elapsed, summary.get("alerts_created", 0))
    return summary


def run_monthly_benchmark(mode: str = "auto") -> None:
    """Monthly deliverable: write the benchmark export."""
    from ..export.writer import export_all

    log.info("=== monthly benchmark export ===")
    for path in export_all(fmt="both"):
        log.info("wrote %s", path)


def run_scheduler(mode: str = "auto", once: bool = False) -> None:
    if once:
        from .runner import run_slot as _run  # re-import for clarity in logs

        slot = _current_slot()
        result = _run(slot, mode=mode)
        print(f"\nSlot '{slot}' complete: {result.get('alerts_created', 0)} alerts, "
              f"{result['elapsed_seconds']}s")
        return

    scheduler = BlockingScheduler(timezone="UTC")

    for slot, hour in SLOT_HOURS.items():
        scheduler.add_job(
            run_slot, CronTrigger(hour=hour, minute=0),
            args=[slot, mode], id=f"collect_{slot}",
            # Overlapping runs would double-count a slot and corrupt shelf
            # share; skip rather than queue if the previous run is still going.
            max_instances=1, coalesce=True, misfire_grace_time=3600,
        )
        log.info("scheduled slot '%s' daily at %02d:00 UTC", slot, hour)

    scheduler.add_job(
        run_monthly_benchmark, CronTrigger(day=1, hour=2, minute=0),
        args=[mode], id="monthly_benchmark", max_instances=1,
    )
    log.info("scheduled monthly benchmark export on the 1st at 02:00 UTC")

    def _shutdown(signum, frame):  # type: ignore[no-untyped-def]
        log.info("shutting down scheduler")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    print("Scheduler running. Slots at "
          + ", ".join(f"{s} {h:02d}:00 UTC" for s, h in SLOT_HOURS.items())
          + ". Ctrl-C to stop.")
    scheduler.start()


def _current_slot() -> str:
    from ..collect.base import current_slot

    return current_slot()
