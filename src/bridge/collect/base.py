"""Shared collector machinery: run lifecycle, SKU upsert, absence tracking.

Platform collectors subclass this and implement only the parts that genuinely
differ — which URLs to hit and how to read a product card. Everything about
*how a run is recorded* lives here, so Newegg and Mercado Libre cannot drift
into recording their results differently.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import platform as platform_config
from ..db.models import FetchLog, Observation, Product, Run, utcnow
from ..db.session import session_scope
from ..normalize.attribution import attribute_brand, attribute_oem, resolve_product_type
from .fetcher import Fetcher

log = logging.getLogger(__name__)


def current_slot(now: datetime | None = None) -> str:
    """Label the 3x-daily collection window.

    Named slots rather than raw timestamps because the brief's cadence is "3x
    daily": comparing today's midday run to yesterday's midday run is the
    meaningful comparison, and that requires the slot to be a first-class
    label rather than something re-derived from an hour field at query time.
    """
    hour = (now or datetime.now(timezone.utc)).hour
    if hour < 11:
        return "morning"
    if hour < 18:
        return "midday"
    return "evening"


class BaseCollector(ABC):
    """One collection run against one platform."""

    run_type: str = "listing"

    def __init__(self, platform_key: str, *, headless: bool = True, max_pages: int | None = None):
        self.platform_key = platform_key
        self.cfg = platform_config(platform_key)
        self.country = self.cfg["country"]
        self.currency = self.cfg["currency"]
        self.locale = self.cfg["locale"]
        self.base_url = self.cfg["base_url"]
        self.headless = headless
        self.max_pages_override = max_pages
        self.run_id: int | None = None

    # -- run lifecycle ------------------------------------------------------

    def start_run(self, session: Session) -> Run:
        run = Run(
            run_type=self.run_type,
            platform=self.platform_key,
            started_at=utcnow(),
            status="running",
            slot=current_slot(),
        )
        session.add(run)
        session.flush()
        self.run_id = run.id
        log.info("[%s] started %s run id=%s slot=%s",
                 self.platform_key, self.run_type, run.id, run.slot)
        return run

    def finish_run(
        self,
        session: Session,
        run: Run,
        *,
        fetcher: Fetcher,
        items_found: int,
        items_parsed: int,
        parse_errors: int,
        notes: str | None = None,
    ) -> None:
        run.finished_at = utcnow()
        run.pages_fetched = fetcher.stats.requests
        run.items_found = items_found
        run.items_parsed = items_parsed
        run.fetch_errors = fetcher.stats.errors
        run.parse_errors = parse_errors
        run.blocked_count = fetcher.stats.blocked
        run.notes = notes

        # Status drives whether metrics trust this run. A run that parsed
        # nothing is "failed" even if every fetch returned 200 — a page that
        # loads but yields no products means the selectors broke, and treating
        # that as a valid zero would read as every brand vanishing from the
        # shelf at once.
        if items_parsed == 0:
            run.status = "failed"
        elif fetcher.stats.blocked or fetcher.stats.errors or parse_errors:
            run.status = "partial"
        else:
            run.status = "ok"

        for entry in fetcher.stats.logs:
            session.add(FetchLog(**{**entry, "run_id": run.id}))

        log.info(
            "[%s] finished run=%s status=%s found=%d parsed=%d blocked=%d errors=%d",
            self.platform_key, run.id, run.status, items_found, items_parsed,
            fetcher.stats.blocked, fetcher.stats.errors,
        )

    # -- SKU persistence ----------------------------------------------------

    def upsert_product(
        self,
        session: Session,
        *,
        platform_sku: str,
        url: str,
        title: str,
        category_product_type: str | None,
        spec_text: str = "",
        badge_text: str = "",
        oem_brand_field: str = "",
    ) -> Product:
        """Insert or update a SKU and its attribution.

        Attribution is recomputed on every sighting rather than cached from
        first sight: retailers edit titles in place, and a title edit that adds
        the processor name is exactly the compliance improvement this project
        exists to detect.
        """
        product_type, is_component = resolve_product_type(category_product_type, title)
        brand_attr = attribute_brand(
            title, is_component=is_component, spec_text=spec_text, badge_text=badge_text
        )
        oem_attr = attribute_oem(
            title, is_component=is_component, brand_field=oem_brand_field, spec_text=spec_text
        )

        product = session.execute(
            select(Product).where(
                Product.platform == self.platform_key,
                Product.platform_sku == platform_sku,
            )
        ).scalar_one_or_none()

        now = utcnow()
        if product is None:
            product = Product(
                platform=self.platform_key,
                platform_sku=platform_sku,
                url=url,
                title=title,
                first_seen_at=now,
            )
            session.add(product)

        # A flip in brand attribution is a real event (a relist or a title
        # rewrite), so it is stamped rather than silently overwritten.
        if product.brand and product.brand != brand_attr.brand and product.brand != "other":
            product.attribution_changed_at = now
            log.info(
                "[%s] attribution changed sku=%s %s -> %s (%s)",
                self.platform_key, platform_sku, product.brand,
                brand_attr.brand, brand_attr.evidence,
            )

        product.url = url or product.url
        product.title = title or product.title
        product.brand = brand_attr.brand
        product.brand_confidence = brand_attr.confidence
        product.brand_evidence = brand_attr.evidence
        product.processor_line = brand_attr.processor_line
        product.processor_tier = brand_attr.processor_tier
        # Only overwrite a known OEM with another known OEM. A product-page
        # pass that fails to find the OEM must not erase what the listing pass
        # already established.
        if oem_attr.oem or product.oem is None:
            product.oem = oem_attr.oem
            product.oem_sub_brand = oem_attr.sub_brand
        product.product_type = product_type
        product.is_component = is_component
        product.last_seen_at = now
        product.consecutive_absences = 0
        product.is_delisted = False

        session.flush()
        return product

    def record_observation(self, session: Session, **kwargs: Any) -> Observation:
        obs = Observation(run_id=self.run_id, observed_at=utcnow(), **kwargs)
        session.add(obs)
        return obs

    def mark_absences(self, session: Session, seen_product_ids: set[int], run: Run) -> int:
        """Increment absence counters for SKUs not seen in this run.

        Only runs on a healthy run: incrementing absences after a blocked or
        truncated run would mark half the catalogue delisted because we failed
        to fetch it, not because it went away.
        """
        if run.status not in ("ok",):
            log.info("[%s] skipping absence marking (run status=%s)",
                     self.platform_key, run.status)
            return 0

        from ..config import scoring_config

        threshold = (
            scoring_config().get("alerts", {}).get("delisted_sku", {}).get("consecutive_absences", 3)
        )
        candidates = session.execute(
            select(Product).where(
                Product.platform == self.platform_key,
                Product.is_delisted.is_(False),
            )
        ).scalars().all()

        newly_delisted = 0
        for product in candidates:
            if product.id in seen_product_ids:
                continue
            product.consecutive_absences += 1
            if product.consecutive_absences >= threshold:
                product.is_delisted = True
                newly_delisted += 1
        return newly_delisted

    # -- subclass contract --------------------------------------------------

    @abstractmethod
    def collect(self) -> dict[str, Any]:
        """Execute one full run and return a summary dict."""

    def run(self) -> dict[str, Any]:
        with session_scope() as session:
            run = self.start_run(session)
            session.commit()
        try:
            return self.collect()
        except Exception as exc:
            log.exception("[%s] run failed", self.platform_key)
            with session_scope() as session:
                if (run_row := session.get(Run, self.run_id)) is not None:
                    run_row.status = "failed"
                    run_row.finished_at = utcnow()
                    run_row.notes = f"{type(exc).__name__}: {exc}"[:1000]
            raise
