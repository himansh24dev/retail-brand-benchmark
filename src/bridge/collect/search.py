"""Share of Voice — search presence and ranking (module 8).

For each keyword in the configured set, the collector records every result
position it sees, not just the tracked brands'. That matters twice over: the
denominator stays honest, and the dashboard can answer the follow-up question
("who is holding the slots we're missing?") instead of only reporting an
absence.

Rank is converted to a DCG-style score at collection time, because position 1
and position 30 are not worth the same and a linear count would say they are.
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any

from sqlalchemy import select as sa_select

from ..config import keywords_config
from ..db.models import Product, Run, SearchRank, utcnow
from ..db.session import session_scope
from ..normalize.attribution import attribute_brand, attribute_oem, resolve_product_type
from .base import BaseCollector
from .fixture_fetcher import make_fetcher
from .parse import absolute_url, node_text, parse_html, select_all, select_one

log = logging.getLogger(__name__)


def dcg_score(rank: int, max_rank: int) -> float:
    """Standard log discount. Rank 1 -> 1.0, rank 10 -> 0.29, beyond cap -> 0."""
    if rank < 1 or rank > max_rank:
        return 0.0
    return 1.0 / math.log2(rank + 1)


class SearchCollector(BaseCollector):
    """Runs the configured keyword set and records result rankings."""

    run_type = "search"

    def __init__(self, platform_key: str, *, headless: bool = True,
                 mode: str = "auto", variant: str | None = None):
        super().__init__(platform_key, headless=headless)
        self.mode = mode
        self.variant = variant

    def collect(self) -> dict[str, Any]:
        fetcher = make_fetcher(self.platform_key, run_id=self.run_id,
                               headless=self.headless, mode=self.mode, variant=self.variant)
        search_cfg = self.cfg["search"]
        listing_selectors = self.cfg["listing"]["selectors"]
        kw_cfg = keywords_config()["keyword_sets"].get(self.platform_key, {})
        max_rank = keywords_config().get("rank_scoring", {}).get("max_rank", 50)

        found = 0
        parsed = 0
        keywords_run = 0

        try:
            for group in ("category", "branded"):
                for entry in kw_cfg.get(group, []):
                    keyword = entry["keyword"]
                    weight = float(entry.get("weight", 1.0))
                    url = self._search_url(search_cfg, keyword, page=1)

                    result = fetcher.fetch(url, wait_for=listing_selectors["item"][0])
                    keywords_run += 1
                    if not result.ok or not result.html:
                        log.warning("[%s] search fetch failed for %r: %s",
                                    self.platform_key, keyword, result.error)
                        continue

                    tree = parse_html(result.html)
                    cards = select_all(tree, listing_selectors["item"])
                    found += len(cards)

                    with session_scope() as session:
                        for rank, card in enumerate(cards[:max_rank], start=1):
                            title = select_one(card, listing_selectors["title"])
                            href = select_one(card, listing_selectors["url"])
                            if not title:
                                continue
                            link = absolute_url(self.base_url, href)

                            product_type, is_component = resolve_product_type(
                                entry.get("product_type"), title
                            )
                            brand_attr = attribute_brand(title, is_component=is_component)
                            oem_attr = attribute_oem(title, is_component=is_component)

                            # Link the ranking back to the SKU when we already
                            # track it, so the SKU explorer can show "this
                            # product ranks #3 for 'gaming laptop'".
                            product_id = self._match_product(session, link)

                            sponsored = bool(
                                select_all(card, listing_selectors.get("sponsored"))
                            )

                            session.add(SearchRank(
                                run_id=self.run_id, platform=self.platform_key,
                                observed_at=utcnow(), keyword=keyword,
                                keyword_group=group, keyword_weight=weight,
                                page=1, rank=rank, product_id=product_id,
                                title=title[:512], brand=brand_attr.brand,
                                oem=oem_attr.oem, is_sponsored=sponsored,
                                dcg_score=dcg_score(rank, max_rank),
                                snapshot_path=result.snapshot_path,
                            ))
                            parsed += 1

            home_found, home_parsed = self._collect_homepage(fetcher)
            found += home_found
            parsed += home_parsed

            with session_scope() as session:
                run = session.get(Run, self.run_id)
                assert run is not None
                self.finish_run(session, run, fetcher=fetcher, items_found=found,
                                items_parsed=parsed, parse_errors=0,
                                notes=f"keywords_run={keywords_run} "
                                      f"homepage_tiles={home_parsed}")

            return {"platform": self.platform_key, "run_id": self.run_id,
                    "keywords": keywords_run, "results_found": found,
                    "results_parsed": parsed, "homepage_tiles": home_parsed}
        finally:
            fetcher.close()

    def _collect_homepage(self, fetcher: Any) -> tuple[int, int]:
        """Record brand presence in the home page's featured product tiles.

        The brief scopes Share of Voice to "home page **and** search results
        pages". Carousel banners are already covered by module 3, but those are
        paid/merchandised slots; the featured grid is the organic surface a
        shopper actually lands on, and a brand can hold banner space while being
        absent from it.

        Rows land in the same table as keyword rankings under their own
        `keyword_group`, so the existing SoV number is untouched and homepage
        presence can be reported separately or blended on request.
        """
        cfg = keywords_config().get("homepage_presence", {}) or {}
        if not cfg.get("enabled", True):
            return 0, 0

        home_cfg = self.cfg.get("homepage", {})
        selectors = home_cfg.get("featured_selectors")
        url = home_cfg.get("url")
        if not selectors or not url:
            return 0, 0

        max_rank = int(cfg.get("max_rank", 24))
        weight = float(cfg.get("blend_weight", 0.25))

        result = fetcher.fetch(url, wait_for=selectors["item"][0])
        if not result.ok or not result.html:
            log.warning("[%s] homepage fetch failed: %s",
                        self.platform_key, result.error)
            return 0, 0

        tree = parse_html(result.html)
        tiles = select_all(tree, selectors["item"])
        if not tiles:
            # Not an error: a homepage legitimately may carry no product grid
            # that day. Logged so a silently-changed selector is still visible.
            log.info("[%s] homepage carried no featured product tiles",
                     self.platform_key)
            return 0, 0

        parsed = 0
        with session_scope() as session:
            for rank, tile in enumerate(tiles[:max_rank], start=1):
                title = select_one(tile, selectors["title"])
                if not title:
                    continue
                link = absolute_url(self.base_url, select_one(tile, selectors["url"]))

                product_type, is_component = resolve_product_type(None, title)
                brand_attr = attribute_brand(title, is_component=is_component)
                oem_attr = attribute_oem(title, is_component=is_component)

                session.add(SearchRank(
                    run_id=self.run_id, platform=self.platform_key,
                    observed_at=utcnow(), keyword="(home page)",
                    keyword_group="homepage", keyword_weight=weight,
                    page=0, rank=rank,
                    product_id=self._match_product(session, link),
                    title=title[:512], brand=brand_attr.brand,
                    oem=oem_attr.oem, is_sponsored=False,
                    dcg_score=dcg_score(rank, max_rank),
                    snapshot_path=result.snapshot_path,
                ))
                parsed += 1

        return len(tiles), parsed

    def _search_url(self, search_cfg: dict, keyword: str, page: int) -> str:
        template = search_cfg["url_template"]
        if self.platform_key == "mercadolibre_br":
            return template.format(keyword=keyword.replace(" ", "-"))
        return template.format(keyword=keyword.replace(" ", "+"), page=page)

    def _match_product(self, session: Any, link: str | None) -> int | None:
        if not link:
            return None
        if m := re.search(r"/p/([A-Za-z0-9]+)|(MLB-?\d+)", link):
            sku = (m.group(1) or m.group(2) or "").replace("-", "")
            if not sku:
                return None
            return session.execute(
                sa_select(Product.id).where(
                    Product.platform == self.platform_key,
                    Product.platform_sku == sku,
                )
            ).scalar_one_or_none()
        return None
