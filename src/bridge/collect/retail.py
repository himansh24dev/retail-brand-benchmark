"""Listing and product-page collection (modules 1, 2, 4, 5, 6)."""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from ..db.models import AuditCheck, BadgeObservation, ProductSpec, Run, utcnow
from ..db.session import session_scope
from ..normalize import audit_checks as checks
from ..normalize.badges import detect_badges
from ..normalize.price import build_price_info, join_fraction_cents, parse_amount, parse_availability
from ..normalize.specs import normalize_spec_key, normalize_spec_value
from ..normalize.text import clean_text
from .base import BaseCollector
from .fixture_fetcher import make_fetcher
from .parse import (
    MissTracker,
    absolute_url,
    extract_spec_table,
    node_text,
    parse_html,
    select_all,
    select_one,
    select_texts,
)

log = logging.getLogger(__name__)


class RetailCollector(BaseCollector):
    """Collects listings and product pages for one platform."""

    run_type = "listing"

    def __init__(
        self,
        platform_key: str,
        *,
        headless: bool = True,
        max_pages: int | None = None,
        mode: str = "auto",
        variant: str | None = None,
        product_pages: bool = True,
        product_page_limit: int | None = None,
    ):
        super().__init__(platform_key, headless=headless, max_pages=max_pages)
        self.mode = mode
        self.variant = variant
        self.product_pages = product_pages
        self.product_page_limit = product_page_limit
        self.tracker = MissTracker()


    def extract_sku(self, url: str) -> str | None:
        raise NotImplementedError

    def parse_card_price(self, card: Any, selectors: dict) -> tuple[float | None, float | None]:
        raise NotImplementedError

    def parse_product_price(self, tree: Any, selectors: dict) -> tuple[float | None, float | None]:
        raise NotImplementedError

    def listing_page_url(self, category_url: str, page: int) -> str:
        raise NotImplementedError


    def collect(self) -> dict[str, Any]:
        fetcher = make_fetcher(
            self.platform_key, run_id=self.run_id, headless=self.headless,
            mode=self.mode, variant=self.variant,
        )
        listing_cfg = self.cfg["listing"]
        selectors = listing_cfg["selectors"]
        max_pages = self.max_pages_override or listing_cfg.get("max_pages", 3)

        items_found = 0
        items_parsed = 0
        parse_errors = 0
        seen_ids: set[int] = set()
        audit_queue: list[tuple[int, str, str, str | None, str]] = []

        try:
            with session_scope() as session:
                run = session.get(Run, self.run_id)
                assert run is not None

                for category in listing_cfg["categories"]:
                    ctype = category["product_type"]
                    rank_offset = 0

                    for page in range(1, max_pages + 1):
                        url = self.listing_page_url(category["url"], page)
                        result = fetcher.fetch(url, wait_for=selectors["item"][0])
                        if not result.ok or not result.html:
                            log.warning("[%s] listing fetch failed %s: %s",
                                        self.platform_key, url, result.error)
                            break

                        tree = parse_html(result.html)
                        cards = select_all(tree, selectors["item"])
                        if not cards:
                            if page == 1:
                                log.error("[%s] no items matched on %s — selector drift?",
                                          self.platform_key, url)
                                parse_errors += 1
                            break

                        items_found += len(cards)
                        for offset, card in enumerate(cards):
                            try:
                                parsed = self._parse_card(
                                    session, card, category=category,
                                    rank=rank_offset + offset + 1, page=page,
                                    selectors=selectors, snapshot=result.snapshot_path,
                                )
                            except Exception:
                                log.exception("[%s] card parse failed", self.platform_key)
                                parse_errors += 1
                                continue
                            if parsed is None:
                                parse_errors += 1
                                continue

                            items_parsed += 1
                            seen_ids.add(parsed[0])
                            audit_queue.append(parsed)

                        rank_offset += len(cards)

                session.flush()

            audited = 0
            if self.product_pages and audit_queue:
                audited = self._audit_products(fetcher, audit_queue)

            with session_scope() as session:
                run = session.get(Run, self.run_id)
                assert run is not None
                self.finish_run(
                    session, run, fetcher=fetcher,
                    items_found=items_found, items_parsed=items_parsed,
                    parse_errors=parse_errors,
                    notes=f"{self.tracker.summary()}; product pages audited={audited}",
                )
                delisted = self.mark_absences(session, seen_ids, run)

            return {
                "platform": self.platform_key,
                "run_id": self.run_id,
                "items_found": items_found,
                "items_parsed": items_parsed,
                "products_audited": audited,
                "parse_errors": parse_errors,
                "newly_delisted": delisted,
                "selector_health": self.tracker.summary(),
            }
        finally:
            fetcher.close()


    def _parse_card(
        self, session: Session, card: Any, *, category: dict, rank: int, page: int,
        selectors: dict, snapshot: str | None,
    ) -> tuple[int, str, str, str | None, str] | None:
        title = select_one(card, selectors["title"], field_name="title", tracker=self.tracker)
        href = select_one(card, selectors["url"], field_name="url", tracker=self.tracker)
        url = absolute_url(self.base_url, href)
        if not title or not url:
            return None

        sku = self.extract_sku(url)
        if not sku:
            return None

        badge_texts = select_texts(card, selectors.get("badge"))
        badge_blob = " ".join(badge_texts)

        feature_text = " ".join(select_texts(card, ["ul.item-features", ".item-features"]))

        product = self.upsert_product(
            session,
            platform_sku=sku, url=url, title=title,
            category_product_type=category["product_type"],
            spec_text=feature_text,
            badge_text=badge_blob,
        )

        price_current, price_was = self.parse_card_price(card, selectors)
        promo_text = select_one(card, selectors.get("promo_text"),
                                field_name="promo_text", tracker=self.tracker)
        price = build_price_info(
            price_current=price_current, price_was=price_was,
            currency=self.currency, promo_text=promo_text,
        )

        rating_raw = select_one(card, selectors.get("rating"))
        rating = None
        if rating_raw and (m := re.search(r"(\d(?:\.\d)?)", rating_raw)):
            rating = float(m.group(1))
        reviews = None
        if (rv := node_text(card)) and (m := re.search(r"\((\d[\d,\.]*)\)", rv)):
            reviews = int(re.sub(r"[^\d]", "", m.group(1)) or 0)

        availability_raw, in_stock = parse_availability(node_text(card))
        sponsored = bool(select_texts(card, selectors.get("sponsored")))

        self.record_observation(
            session,
            product_id=product.id,
            price_current=price.price_current, price_was=price.price_was,
            currency=price.currency, discount_pct=price.discount_pct,
            has_promo=price.has_promo, promo_text=price.promo_text,
            availability=availability_raw, in_stock=in_stock,
            listing_rank=rank, listing_page=page, listing_category=category["name"],
            is_sponsored=sponsored, rating=rating, review_count=reviews,
            source_page="listing", snapshot_path=snapshot,
        )

        badge_findings = detect_badges(
            brand=product.brand, processor_line=product.processor_line,
            product_type=product.product_type, page_type="listing",
            badge_text=badge_blob, exclude_text=title,
        )
        for finding in badge_findings:
            session.add(BadgeObservation(
                run_id=self.run_id, product_id=product.id, observed_at=utcnow(),
                brand=finding.brand, badge_name=finding.badge_name, page_type="listing",
                is_eligible=finding.is_eligible, is_present=finding.is_present,
                evidence=finding.evidence,
            ))

        for result in (
            checks.check_s1(brand=product.brand, title=title,
                            processor_line=product.processor_line),
            checks.check_s2(brand=product.brand, badge_findings=badge_findings),
        ):
            session.add(AuditCheck(
                run_id=self.run_id, product_id=product.id, observed_at=utcnow(),
                check_code=result.code, page_type=result.page_type,
                passed=result.passed, evidence=result.evidence, snapshot_path=snapshot,
                brand=product.brand, product_type=product.product_type,
            ))

        return (product.id, url, product.brand, product.processor_line, product.product_type)


    def _audit_products(
        self, fetcher: Any, queue: list[tuple[int, str, str, str | None, str]]
    ) -> int:
        """Fetch each SKU's product page and evaluate P1-P5 plus specs."""
        from ..config import tracked_brands

        targets = [row for row in queue if row[2] in tracked_brands()]
        if self.product_page_limit:
            targets = targets[: self.product_page_limit]

        selectors = self.cfg["product"]["selectors"]
        audited = 0

        for product_id, url, brand, processor_line, product_type in targets:
            result = fetcher.fetch(url, wait_for=selectors["title"][0])
            page_loaded = bool(result.ok and result.html)

            with session_scope() as session:
                if not page_loaded:
                    for unknown in checks.unknown_product_checks(brand):
                        session.add(AuditCheck(
                            run_id=self.run_id, product_id=product_id, observed_at=utcnow(),
                            check_code=unknown.code, page_type="product",
                            passed=None, evidence=unknown.evidence,
                            brand=brand, product_type=product_type,
                        ))
                    continue

                tree = parse_html(result.html)
                title = select_one(tree, selectors["title"],
                                   field_name="p_title", tracker=self.tracker) or ""
                specs_raw = extract_spec_table(tree, selectors.get("spec_table"))
                badge_texts = select_texts(tree, selectors.get("badge"))
                brand_media = " ".join(select_texts(tree, selectors.get("rich_media_brand")))
                oem_media_present = bool(select_all(tree, selectors.get("rich_media_oem")))

                price_current, price_was = self.parse_product_price(tree, selectors)
                promo_text = select_one(tree, selectors.get("promo_text"))
                price = build_price_info(
                    price_current=price_current, price_was=price_was,
                    currency=self.currency, promo_text=promo_text,
                )
                availability_raw, in_stock = parse_availability(
                    select_one(tree, selectors.get("availability"))
                )
                self.record_observation(
                    session,
                    product_id=product_id,
                    price_current=price.price_current, price_was=price.price_was,
                    currency=price.currency, discount_pct=price.discount_pct,
                    has_promo=price.has_promo, promo_text=price.promo_text,
                    availability=availability_raw, in_stock=in_stock,
                    source_page="product", snapshot_path=result.snapshot_path,
                )

                self._store_specs(session, product_id, specs_raw)

                badge_findings = detect_badges(
                    brand=brand, processor_line=processor_line, product_type=product_type,
                    page_type="product", badge_text=" ".join(badge_texts),
                    exclude_text=title,
                )
                for finding in badge_findings:
                    session.add(BadgeObservation(
                        run_id=self.run_id, product_id=product_id, observed_at=utcnow(),
                        brand=finding.brand, badge_name=finding.badge_name,
                        page_type="product", is_eligible=finding.is_eligible,
                        is_present=finding.is_present, evidence=finding.evidence,
                    ))

                results = [
                    checks.check_p1(brand=brand, title=title, processor_line=processor_line),
                    checks.check_p2(brand=brand, badge_findings=badge_findings),
                    checks.check_p3(brand=brand, specs=specs_raw, processor_line=processor_line),
                    checks.check_p4(brand=brand, brand_media_text=brand_media,
                                    page_loaded=True),
                    checks.check_p5(brand=brand, oem_media_present=oem_media_present,
                                    page_loaded=True),
                ]
                for result_row in results:
                    session.add(AuditCheck(
                        run_id=self.run_id, product_id=product_id, observed_at=utcnow(),
                        check_code=result_row.code, page_type="product",
                        passed=result_row.passed, evidence=result_row.evidence,
                        snapshot_path=result.snapshot_path,
                        brand=brand, product_type=product_type,
                    ))
                audited += 1

        return audited

    def _store_specs(self, session: Session, product_id: int, specs: dict[str, str]) -> None:
        """Persist specs only when the set differs from what we already hold."""
        if not specs:
            return
        from sqlalchemy import select as sa_select

        existing = session.execute(
            sa_select(ProductSpec.key_raw, ProductSpec.value_raw)
            .where(ProductSpec.product_id == product_id)
        ).all()
        current = {k: v for k, v in existing}
        incoming = {k: (normalize_spec_value(v) or "") for k, v in specs.items()}
        if current and current == incoming:
            return

        for key_raw, value in specs.items():
            session.add(ProductSpec(
                product_id=product_id, run_id=self.run_id, observed_at=utcnow(),
                key_raw=clean_text(key_raw)[:128],
                key_normalized=normalize_spec_key(key_raw),
                value_raw=clean_text(value)[:512],
                value_normalized=normalize_spec_value(value),
            ))


class NeweggCollector(RetailCollector):
    """Newegg US. SKUs look like N82E16834156001 and appear in /p/<sku>."""

    _SKU_RE = re.compile(r"/p/([A-Za-z0-9]+)")

    def __init__(self, **kwargs: Any):
        super().__init__("newegg_us", **kwargs)

    def extract_sku(self, url: str) -> str | None:
        if m := self._SKU_RE.search(url):
            return m.group(1)
        if m := re.search(r"[?&]Item=([A-Za-z0-9]+)", url):
            return m.group(1)
        return None

    def listing_page_url(self, category_url: str, page: int) -> str:
        if page == 1:
            return category_url
        joiner = "&" if "?" in category_url else "?"
        return f"{category_url}{joiner}page={page}"

    def _price_from(self, root: Any, chain: list[str] | None) -> float | None:
        """Newegg splits price as <strong>1,299</strong><sup>.99</sup>."""
        for selector in chain or ():
            node = root.css_first(selector.split("@")[0])
            if node is None:
                continue
            strong = node.css_first("strong")
            sup = node.css_first("sup")
            if strong is not None:
                whole = clean_text(strong.text())
                cents = clean_text(sup.text()).lstrip(".") if sup is not None else "00"
                if value := parse_amount(f"{whole}.{cents}", self.locale):
                    return value
            if value := parse_amount(node.text(), self.locale):
                return value
        return None

    def parse_card_price(self, card: Any, selectors: dict) -> tuple[float | None, float | None]:
        current = self._price_from(card, selectors.get("price_current"))
        was = self._price_from(card, selectors.get("price_was"))
        self.tracker.record("price_current", current is not None)
        return current, was

    def parse_product_price(self, tree: Any, selectors: dict) -> tuple[float | None, float | None]:
        current = self._price_from(tree, selectors.get("price_current"))
        was = self._price_from(tree, selectors.get("price_was"))
        return current, was


class MercadoLibreCollector(RetailCollector):
    """Mercado Libre Brazil. SKUs are MLB-prefixed item ids."""

    _SKU_RE = re.compile(r"(MLB-?\d+)")

    def __init__(self, **kwargs: Any):
        super().__init__("mercadolibre_br", **kwargs)

    def extract_sku(self, url: str) -> str | None:
        if m := self._SKU_RE.search(url):
            return m.group(1).replace("-", "")
        return None

    def listing_page_url(self, category_url: str, page: int) -> str:
        if page == 1:
            return category_url
        step = self.cfg["listing"].get("pagination_step", 50)
        return f"{category_url}_Desde_{(page - 1) * step + 1}"

    def _price_from(self, root: Any, chain: list[str] | None) -> float | None:
        """ML renders R$ 5.499,90 as separate fraction and cents nodes."""
        for selector in chain or ():
            css = selector.split("@")[0]
            node = root.css_first(css)
            if node is None:
                continue
            fraction = clean_text(node.text())
            cents_node = None
            parent = node.parent
            if parent is not None:
                cents_node = parent.css_first(".andes-money-amount__cents")
            cents = clean_text(cents_node.text()) if cents_node is not None else None
            if value := join_fraction_cents(fraction, cents, self.locale):
                return value
        return None

    def parse_card_price(self, card: Any, selectors: dict) -> tuple[float | None, float | None]:
        current = self._price_from(card, selectors.get("price_current"))
        was = self._price_from(card, selectors.get("price_was"))
        self.tracker.record("price_current", current is not None)
        return current, was

    def parse_product_price(self, tree: Any, selectors: dict) -> tuple[float | None, float | None]:
        current = self._price_from(tree, selectors.get("price_current"))
        was = self._price_from(tree, selectors.get("price_was"))
        return current, was


COLLECTORS = {
    "newegg_us": NeweggCollector,
    "mercadolibre_br": MercadoLibreCollector,
}
