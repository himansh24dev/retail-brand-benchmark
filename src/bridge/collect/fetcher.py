"""HTTP/browser fetch layer with rate limiting, block detection and evidence.

Two strategies, chosen per platform in config:

  http     — plain HTTP/2 via httpx. Fast and cheap. Works on Mercado Libre,
             which server-renders most listing content.
  browser  — a real Chromium via Playwright. Needed for Newegg, which gates
             listings behind a JS interstitial.

A platform declares its preferred strategy but is not locked to it: an `http`
platform that trips a block signal escalates to `browser` automatically for the
rest of the run. That single fallback is what keeps a collection run alive when
a site tightens its defences mid-week, instead of returning a week of zeros.

Every response is written to a gzipped snapshot on disk and referenced from the
database. That is what makes any number in the dashboard auditable back to the
exact bytes it came from — the difference between "AMD's shelf share dropped"
and "we can prove AMD's shelf share dropped".
"""

from __future__ import annotations

import gzip
import hashlib
import logging
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from ..config import RAW_DIR, platform as platform_config

log = logging.getLogger(__name__)

# A small pool of current desktop UAs. Rotating within a run makes traffic look
# less like a single scripted client. This is politeness-preserving variation,
# not evasion: we still obey a strict rate limit and back off hard on blocks.
_USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36",
)

# Below this, a "successful" response is almost certainly an error page or an
# interstitial rather than real content.
_MIN_PLAUSIBLE_BYTES = 2_000


@dataclass
class FetchResult:
    url: str
    html: str | None
    status_code: int | None
    ok: bool
    blocked: bool = False
    error: str | None = None
    duration_ms: int = 0
    snapshot_path: str | None = None
    method: str = "http"

    @property
    def content_bytes(self) -> int:
        return len(self.html or "")


@dataclass
class FetchStats:
    requests: int = 0
    ok: int = 0
    blocked: int = 0
    errors: int = 0
    logs: list[dict[str, Any]] = field(default_factory=list)


class RateLimiter:
    """Per-platform request pacing with jitter.

    Jitter matters as much as the rate: perfectly periodic requests are a
    stronger bot signal than the volume itself.
    """

    def __init__(self, requests_per_minute: int, jitter_seconds: tuple[float, float]):
        self.min_interval = 60.0 / max(requests_per_minute, 1)
        self.jitter_low, self.jitter_high = jitter_seconds
        self._last_request: float = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_request
        delay = max(0.0, self.min_interval - elapsed)
        delay += random.uniform(self.jitter_low, self.jitter_high)
        if delay > 0:
            time.sleep(delay)
        self._last_request = time.monotonic()


class Fetcher:
    """Fetches pages for one platform, honouring its rate limit and blocks.

    Use as a context manager so the browser is torn down deterministically:

        with Fetcher("newegg_us") as f:
            result = f.fetch(url)
    """

    def __init__(
        self,
        platform_key: str,
        *,
        run_id: int | None = None,
        headless: bool = True,
        proxy: str | None = None,
    ):
        self.platform_key = platform_key
        self.cfg = platform_config(platform_key)
        self.run_id = run_id
        self.headless = headless
        self.strategy = self.cfg.get("fetch_strategy", "http")
        self.locale = self.cfg.get("locale", "en-US")

        rl = self.cfg.get("rate_limit", {})
        self.limiter = RateLimiter(
            rl.get("requests_per_minute", 10),
            tuple(rl.get("jitter_seconds", [2, 5])),
        )
        self.block_backoff = rl.get("block_backoff_seconds", 600)
        self.block_signals = tuple(s.lower() for s in self.cfg.get("block_signals", []))
        self.block_url_signals = tuple(
            s.lower() for s in self.cfg.get("block_url_signals", [])
        )

        # Proxy is opt-in and env-driven so no credential is ever committed.
        # Both target platforms reject datacenter IPs outright; pointing this
        # at a residential/scraping-API endpoint is the only change needed to
        # move from fixtures to live collection.
        self.proxy = proxy or os.environ.get(
            f"BRIDGE_PROXY_{platform_key.upper()}"
        ) or os.environ.get("BRIDGE_PROXY")

        self.stats = FetchStats()
        self._user_agent = random.choice(_USER_AGENTS)
        self._client: httpx.Client | None = None
        self._playwright = None
        self._browser = None
        self._context = None
        # Set once a block is seen, so an http-first platform stops retrying a
        # strategy that is currently failing.
        self._escalated_to_browser = False
        self._consecutive_blocks = 0

    # -- lifecycle ----------------------------------------------------------

    def __enter__(self) -> "Fetcher":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
        for attr in ("_context", "_browser"):
            obj = getattr(self, attr)
            if obj is not None:
                try:
                    obj.close()
                except Exception:  # pragma: no cover - teardown is best-effort
                    pass
                setattr(self, attr, None)
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:  # pragma: no cover
                pass
            self._playwright = None

    # -- lazy resources -----------------------------------------------------

    def _http_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                http2=True,
                follow_redirects=True,
                proxy=self.proxy,
                timeout=httpx.Timeout(30.0, connect=15.0),
                headers={
                    "User-Agent": self._user_agent,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                              "image/avif,image/webp,*/*;q=0.8",
                    "Accept-Language": f"{self.locale},en;q=0.7",
                    # Accept-Encoding is deliberately NOT set here. httpx
                    # advertises exactly the codecs it can decode; hand-setting
                    # it to include 'br' without the brotli package installed
                    # makes the server return brotli that httpx hands back as
                    # mojibake in .text, with a perfectly healthy 200 status.
                    "Cache-Control": "no-cache",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "none",
                    "Upgrade-Insecure-Requests": "1",
                },
            )
        return self._client

    def _browser_context(self):
        """Start Chromium once and reuse the context across the run.

        Cold-starting a browser per URL would cost more than the rate limit
        itself, and a persistent context keeps cookies, which is what lets
        Newegg's interstitial stay solved after the first pass.
        """
        if self._context is not None:
            return self._context

        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            proxy={"server": self.proxy} if self.proxy else None,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )
        self._context = self._browser.new_context(
            user_agent=self._user_agent,
            locale=self.locale,
            viewport={"width": 1920, "height": 1080},
            extra_http_headers={"Accept-Language": f"{self.locale},en;q=0.7"},
        )
        # navigator.webdriver is the single most-checked automation tell.
        self._context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        # Images and fonts are pure cost here: we parse markup, never pixels.
        # Blocking them cuts page weight by roughly an order of magnitude.
        self._context.route(
            "**/*",
            lambda route: route.abort()
            if route.request.resource_type in ("image", "media", "font")
            else route.continue_(),
        )
        return self._context

    # -- fetching -----------------------------------------------------------

    def fetch(
        self,
        url: str,
        *,
        wait_for: str | None = None,
        force_strategy: str | None = None,
        save_snapshot: bool = True,
        max_retries: int = 2,
    ) -> FetchResult:
        """Fetch one URL, with retries, block detection and snapshotting."""
        strategy = force_strategy or (
            "browser" if self._escalated_to_browser else self.strategy
        )

        result: FetchResult | None = None
        for attempt in range(max_retries + 1):
            self.limiter.wait()
            started = time.monotonic()

            if strategy == "browser":
                result = self._fetch_browser(url, wait_for=wait_for)
            else:
                result = self._fetch_http(url)
            result.duration_ms = int((time.monotonic() - started) * 1000)

            self.stats.requests += 1

            if result.blocked:
                self._handle_block(url, attempt, max_retries)
                # Escalate an http platform to a real browser once, then retry.
                if strategy == "http" and not self._escalated_to_browser:
                    log.warning("[%s] escalating to browser after block", self.platform_key)
                    self._escalated_to_browser = True
                    strategy = "browser"
                    continue
                if attempt < max_retries:
                    continue

            elif result.ok:
                self._consecutive_blocks = 0
                break

            elif attempt < max_retries:
                # Transient failure — exponential backoff before retrying.
                time.sleep(min(2 ** attempt * 3, 30))
                continue

        assert result is not None
        if result.blocked:
            self.stats.blocked += 1
        elif result.ok:
            self.stats.ok += 1
        else:
            self.stats.errors += 1

        if save_snapshot and result.html:
            result.snapshot_path = self._save_snapshot(url, result.html)

        self.stats.logs.append(
            {
                "run_id": self.run_id,
                "url": url,
                "method": result.method,
                "status_code": result.status_code,
                "ok": result.ok,
                "blocked": result.blocked,
                "error": result.error,
                "duration_ms": result.duration_ms,
                "content_bytes": result.content_bytes,
                "snapshot_path": result.snapshot_path,
            }
        )
        return result

    def _fetch_http(self, url: str) -> FetchResult:
        try:
            response = self._http_client().get(url)
            html = response.text
            # str(response.url) is the URL *after* redirects — the challenge
            # page, not the one we asked for.
            blocked = self._is_blocked(html, response.status_code, str(response.url))
            ok = (
                response.status_code == 200
                and not blocked
                and len(html) >= _MIN_PLAUSIBLE_BYTES
            )
            return FetchResult(
                url=url,
                html=html,
                status_code=response.status_code,
                ok=ok,
                blocked=blocked,
                method="http",
                error=None if ok else f"status={response.status_code} len={len(html)}",
            )
        except Exception as exc:
            return FetchResult(
                url=url, html=None, status_code=None, ok=False,
                error=f"{type(exc).__name__}: {exc}", method="http",
            )

    def _fetch_browser(self, url: str, *, wait_for: str | None = None) -> FetchResult:
        try:
            page = self._browser_context().new_page()
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                if wait_for:
                    try:
                        page.wait_for_selector(wait_for, timeout=15_000)
                    except Exception:
                        # A missing selector is a parse-stage concern, not a
                        # fetch failure — the page may simply be empty. Keep
                        # the HTML so the parser can log what it actually saw.
                        log.debug("[%s] wait_for %r timed out on %s",
                                  self.platform_key, wait_for, url)
                # Listing pages lazy-load below the fold; without a scroll the
                # tail of the page is empty and shelf counts come out short.
                page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.6)")
                page.wait_for_timeout(1200)

                html = page.content()
                status = response.status if response else None
                blocked = self._is_blocked(html, status, page.url)
                ok = (
                    (status is None or status == 200)
                    and not blocked
                    and len(html) >= _MIN_PLAUSIBLE_BYTES
                )
                return FetchResult(
                    url=url, html=html, status_code=status, ok=ok, blocked=blocked,
                    method="browser",
                    error=None if ok else f"status={status} len={len(html)}",
                )
            finally:
                page.close()
        except Exception as exc:
            return FetchResult(
                url=url, html=None, status_code=None, ok=False,
                error=f"{type(exc).__name__}: {exc}", method="browser",
            )

    # -- block handling -----------------------------------------------------

    def _is_blocked(
        self, html: str | None, status_code: int | None, final_url: str | None = None
    ) -> bool:
        if status_code in (403, 429, 503):
            return True

        # URL-based detection first. Both target platforms redirect to a
        # challenge page and serve it with a perfectly healthy 200 and a
        # sizeable body — Newegg to /areyouahuman, Mercado Libre to
        # /gz/account-verification. Body-text signals alone miss this, which
        # would let a run record "0 products found" as a real shelf collapse
        # rather than as a block.
        if final_url:
            lowered = final_url.lower()
            if any(sig in lowered for sig in self.block_url_signals):
                return True

        if not html:
            return False
        # Only the head of the document: interstitials are served *instead of*
        # content, so the signal is always early. Scanning a full 2 MB product
        # page for these strings would also false-positive on user reviews
        # containing words like "access denied".
        head = html[:8_000].lower()
        return any(signal in head for signal in self.block_signals)

    def _handle_block(self, url: str, attempt: int, max_retries: int) -> None:
        self._consecutive_blocks += 1
        log.warning(
            "[%s] blocked on %s (attempt %d/%d, consecutive=%d)",
            self.platform_key, url, attempt + 1, max_retries + 1, self._consecutive_blocks,
        )
        if attempt >= max_retries:
            return
        # Escalating backoff. Repeated blocks mean the site has flagged us;
        # continuing at the normal rate risks a hard IP ban that would cost the
        # rest of the week's history.
        backoff = min(self.block_backoff * self._consecutive_blocks, 3600)
        log.warning("[%s] backing off %ds", self.platform_key, backoff)
        time.sleep(backoff)
        self._user_agent = random.choice(_USER_AGENTS)

    # -- evidence store -----------------------------------------------------

    def _save_snapshot(self, url: str, html: str) -> str:
        """Persist raw HTML, gzipped, partitioned by platform and UTC date.

        The URL hash in the filename makes snapshots idempotent within a run and
        keeps the path stable enough to find by hand during a walkthrough.
        """
        now = datetime.now(timezone.utc)
        digest = hashlib.sha256(url.encode()).hexdigest()[:16]
        directory: Path = (
            RAW_DIR / self.platform_key / now.strftime("%Y-%m-%d") / f"run{self.run_id or 0}"
        )
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{now.strftime('%H%M%S')}_{digest}.html.gz"
        try:
            with gzip.open(path, "wt", encoding="utf-8", compresslevel=6) as fh:
                fh.write(html)
        except OSError as exc:  # disk full, permissions — never fail the run
            log.error("snapshot write failed for %s: %s", url, exc)
            return ""
        return str(path.relative_to(RAW_DIR.parent))
