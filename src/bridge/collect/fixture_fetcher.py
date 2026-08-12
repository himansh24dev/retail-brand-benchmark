"""Fixture transport — serves saved HTML in place of live requests."""

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
    """Drop-in replacement for `Fetcher` that reads from disk."""

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
    """Return the transport for this run."""
    from .fetcher import Fetcher

    if mode == "live":
        return Fetcher(platform_key, run_id=run_id, headless=headless)
    if mode == "fixture":
        return FixtureFetcher(platform_key, run_id=run_id, variant=variant)

    if (FIXTURE_DIR / platform_key).exists():
        log.info("[%s] using fixture transport (variant=%s)", platform_key, variant or "base")
        return FixtureFetcher(platform_key, run_id=run_id, variant=variant)
    return Fetcher(platform_key, run_id=run_id, headless=headless)
