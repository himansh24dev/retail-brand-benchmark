"""Homepage banner tracking (module 3).

Banners are the hardest thing in this project to attribute. A product listing
has a title, a spec table and a badge; a banner has an image, an alt attribute
and a link. So attribution runs over alt text plus the link URL, and the
resulting `brand_confidence` is stored and surfaced rather than hidden — a
banner-share chart built on weak attribution should look weak.

Note the deliberate difference from product attribution: here a discrete-GPU
token *does* attribute. "GeForce RTX 40 Series Deals" is an NVIDIA banner, not
an unattributed one, because the banner's subject is the silicon itself rather
than a device containing it.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ..db.models import BannerObservation, Run, utcnow
from ..db.session import session_scope
from ..normalize.attribution import attribute_brand, attribute_oem
from ..normalize.badges import detect_badges
from ..normalize.text import clean_text
from .base import BaseCollector
from .fixture_fetcher import make_fetcher
from .parse import absolute_url, parse_html, select_all, select_one, select_texts

log = logging.getLogger(__name__)

_DISCOUNT_RE = re.compile(
    r"(\d{1,3}\s*%\s*(?:off|de\s*desconto)|save\s*(?:up\s*to\s*)?\$?\d+|"
    r"até\s*\d{1,3}\s*%|up\s*to\s*\$?\d+|\bofertas?\b|\bdeals?\b|\bsale\b)",
    re.IGNORECASE,
)


class BannerCollector(BaseCollector):
    """Captures the homepage banner carousel for one platform."""

    run_type = "banner"

    def __init__(self, platform_key: str, *, headless: bool = True,
                 mode: str = "auto", variant: str | None = None):
        super().__init__(platform_key, headless=headless)
        self.mode = mode
        self.variant = variant

    def collect(self) -> dict[str, Any]:
        fetcher = make_fetcher(self.platform_key, run_id=self.run_id,
                               headless=self.headless, mode=self.mode, variant=self.variant)
        home_cfg = self.cfg["homepage"]
        selectors = home_cfg["banner_selectors"]

        found = 0
        parsed = 0
        try:
            result = fetcher.fetch(home_cfg["url"], wait_for=selectors["slide"][0])
            with session_scope() as session:
                run = session.get(Run, self.run_id)
                assert run is not None

                if result.ok and result.html:
                    tree = parse_html(result.html)
                    containers = select_all(tree, selectors.get("container"))
                    # Fall back to searching the whole document: a homepage
                    # redesign that renames the carousel wrapper should not
                    # silently produce "zero banners", which would read as a
                    # brand losing all banner share.
                    scope = containers[0] if containers else tree
                    slides = select_all(scope, selectors["slide"])
                    found = len(slides)
                    if not slides:
                        log.error("[%s] no banner slides matched — selector drift?",
                                  self.platform_key)

                    for position, slide in enumerate(slides, start=1):
                        alt = select_one(slide, selectors.get("alt")) or ""
                        href = select_one(slide, selectors.get("link"))
                        link = absolute_url(self.base_url, href)
                        image = select_one(slide, selectors.get("image"))

                        # Link slug carries brand intent even when alt text is
                        # generic ("/promotions/amd-ryzen-week").
                        haystack = clean_text(f"{alt} {link or ''}".replace("-", " ").replace("/", " "))

                        brand_attr = attribute_brand(haystack, is_component=True)
                        oem_attr = attribute_oem(haystack, is_component=False)
                        badges = detect_badges(
                            brand=brand_attr.brand, processor_line=brand_attr.processor_line,
                            product_type=None, page_type="banner", badge_text=alt,
                        )
                        discount = _DISCOUNT_RE.search(alt)

                        session.add(BannerObservation(
                            run_id=self.run_id, platform=self.platform_key,
                            observed_at=utcnow(), slot_position=position,
                            slot_type="hero" if position == 1 else "carousel",
                            image_url=image, link_url=link, alt_text=alt or None,
                            brand=brand_attr.brand if brand_attr.brand != "other" else None,
                            brand_confidence=brand_attr.confidence,
                            oem=oem_attr.oem,
                            has_link=bool(link),
                            has_discount=bool(discount),
                            discount_text=discount.group(0) if discount else None,
                            badges_detected=", ".join(
                                b.badge_name for b in badges if b.is_present
                            ) or None,
                            snapshot_path=result.snapshot_path,
                        ))
                        parsed += 1

                self.finish_run(session, run, fetcher=fetcher, items_found=found,
                                items_parsed=parsed, parse_errors=found - parsed)

            return {"platform": self.platform_key, "run_id": self.run_id,
                    "banners_found": found, "banners_parsed": parsed}
        finally:
            fetcher.close()
