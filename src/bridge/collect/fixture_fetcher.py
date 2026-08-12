"""Fixture transport — serves saved HTML in place of live requests.

Live collection from this environment is blocked: both target platforms redirect
datacenter IPs to a challenge page (see docs/DATA_SOURCING.md). This fetcher
lets the entire pipeline run, be tested and be demonstrated end-to-end without
pretending the data is live.

It deliberately mirrors `Fetcher`'s interface exactly — same `fetch()` signature,
same `FetchResult`, same `stats`. Collectors therefore contain no branch on
"are we in fixture mode": swapping transports is a constructor argument, and the
parsing path under test is byte-for-byte the one that will run against live HTML.

What this does NOT do is fabricate metrics. Fixtures are inputs to the real
parsers; every number downstream is computed by the same code that would run in
production. The honesty boundary is that the *inputs* are synthetic, and that is
stated wherever the numbers are shown.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from ..config import PROJECT_ROOT
from .fetcher import FetchResult, FetchStats

log = logging.getLogger(__name__)

FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures"


class FixtureFetcher:
    """Drop-in replacement for `Fetcher` that reads from disk.

    Fixtures are resolved by URL through a per-platform `index.json` mapping,
    falling back to a deterministic hash of the URL. A miss returns a normal
    failed FetchResult rather than raising, so a partially-populated fixture set
    exercises the collector's error handling too.
    """

    def __init__(
        self,
        platform_key: str,
        *,
        run_id: int | None = None,
        headless: bool = True,
        proxy: str | None = None,
        variant: str | None = None,
    ):
        self.platform_key = platform_key
        self.run_id = run_id
        self.stats = FetchStats()
        self.root = FIXTURE_DIR / platform_key
        # A variant selects an alternate snapshot of the same URLs, which is how
        # multi-run history is produced without inventing numbers at the metrics
        # layer: each run reads a different point-in-time capture.
        self.variant = variant
        self._index = self._load_index()

    def __enter__(self) -> "FixtureFetcher":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        return None

    def _load_index(self) -> dict[str, str]:
        index_path = self.root / "index.json"
        if not index_path.exists():
            return {}
        try:
            return json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.error("fixture index unreadable at %s: %s", index_path, exc)
            return {}

    def _candidate_paths(self, url: str) -> list[Path]:
        """Fixture lookup order, most-specific first."""
        digest = hashlib.sha256(url.encode()).hexdigest()[:16]
        names: list[str] = []
        if mapped := self._index.get(url):
            names.append(mapped)
        names.append(f"{digest}.html")

        out: list[Path] = []
        for name in names:
            stem = name[:-5] if name.endswith(".html") else name
            if self.variant:
                out.append(self.root / f"{stem}.{self.variant}.html")
                out.append(self.root / f"{stem}.{self.variant}.html.gz")
            out.append(self.root / f"{stem}.html")
            out.append(self.root / f"{stem}.html.gz")
        return out

    def fetch(
        self,
        url: str,
        *,
        wait_for: str | None = None,
        force_strategy: str | None = None,
        save_snapshot: bool = True,
        max_retries: int = 2,
    ) -> FetchResult:
        started = time.monotonic()
        self.stats.requests += 1

        html: str | None = None
        used: Path | None = None
        for path in self._candidate_paths(url):
            if not path.exists():
                continue
            try:
                if path.suffix == ".gz":
                    html = gzip.open(path, "rt", encoding="utf-8").read()
                else:
                    html = path.read_text(encoding="utf-8")
                used = path
                break
            except OSError as exc:
                log.error("fixture read failed %s: %s", path, exc)

        # A small delay keeps run timings and the scheduler's pacing realistic
        # rather than completing a "3x daily" run in 40 milliseconds.
        time.sleep(random.uniform(0.01, 0.05))
        duration_ms = int((time.monotonic() - started) * 1000)

        if html is None:
            self.stats.errors += 1
            result = FetchResult(
                url=url, html=None, status_code=404, ok=False,
                error="fixture not found", duration_ms=duration_ms, method="fixture",
            )
        else:
            self.stats.ok += 1
            result = FetchResult(
                url=url, html=html, status_code=200, ok=True,
                duration_ms=duration_ms, method="fixture",
                snapshot_path=str(used.relative_to(PROJECT_ROOT)) if used else None,
            )

        self.stats.logs.append(
            {
                "run_id": self.run_id,
                "url": url,
                "method": "fixture",
                "status_code": result.status_code,
                "ok": result.ok,
                "blocked": False,
                "error": result.error,
                "duration_ms": duration_ms,
                "content_bytes": result.content_bytes,
                "snapshot_path": result.snapshot_path,
            }
        )
        return result


def make_fetcher(
    platform_key: str,
    *,
    run_id: int | None = None,
    headless: bool = True,
    mode: str = "auto",
    variant: str | None = None,
):
    """Return the transport for this run.

    mode:
      live     — always use the network
      fixture  — always use saved HTML
      auto     — fixture when a fixture set exists, else live

    `auto` is the default so a developer with no credentials gets a working
    pipeline, while a scheduled run in an environment with proxy access picks
    up the network path without a code change.
    """
    from .fetcher import Fetcher

    if mode == "live":
        return Fetcher(platform_key, run_id=run_id, headless=headless)
    if mode == "fixture":
        return FixtureFetcher(platform_key, run_id=run_id, variant=variant)

    if (FIXTURE_DIR / platform_key).exists():
        log.info("[%s] using fixture transport (variant=%s)", platform_key, variant or "base")
        return FixtureFetcher(platform_key, run_id=run_id, variant=variant)
    return Fetcher(platform_key, run_id=run_id, headless=headless)
