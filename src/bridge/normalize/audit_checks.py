"""Rubric evaluation for module 2 (retailer audits)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..config import brand_display_names, tracked_brands
from .badges import BadgeFinding, has_any_badge
from .specs import spec_mentions_brand_or_line
from .text import clean_text

_GENERATION_RE = re.compile(
    r"\b(\d{1,2}(?:th|st|nd|rd)\s*gen(?:eration)?|"
    r"gen\s*\d{1,2}|"
    r"[0-9]{4,5}[A-Z]{1,3}\b|"
    r"[MX][1-9](?:\s*(?:pro|max|ultra))?\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CheckResult:
    code: str
    page_type: str
    passed: bool | None
    evidence: str | None = None


def _title_names_brand(title: str, brand: str, processor_line: str | None) -> tuple[bool, str | None]:
    text = clean_text(title)
    if not text:
        return False, None
    low = text.lower()

    if processor_line and processor_line.lower() in low:
        return True, f"line:'{processor_line}'"
    display = brand_display_names().get(brand, brand)
    if display.lower() in low:
        return True, f"brand:'{display}'"
    return False, None


def check_s1(*, brand: str, title: str, processor_line: str | None) -> CheckResult:
    """S1: listing title includes the brand name and/or its processor line."""
    if brand not in tracked_brands():
        return CheckResult("S1", "listing", None, "brand not tracked")
    passed, evidence = _title_names_brand(title, brand, processor_line)
    return CheckResult("S1", "listing", passed, evidence or "no brand/line token in title")


def check_s2(*, brand: str, badge_findings: list[BadgeFinding]) -> CheckResult:
    """S2: a brand badge is shown on the listing tile."""
    if brand not in tracked_brands():
        return CheckResult("S2", "listing", None, "brand not tracked")
    present = has_any_badge(badge_findings)
    if present:
        shown = next(f.badge_name for f in badge_findings if f.is_present)
        return CheckResult("S2", "listing", True, f"badge:'{shown}'")

    if not any(f.is_eligible for f in badge_findings):
        return CheckResult("S2", "listing", None, "no eligible badge for this SKU")
    eligible = ", ".join(f.badge_name for f in badge_findings if f.is_eligible)
    return CheckResult("S2", "listing", False, f"eligible but absent: {eligible}")


def check_p1(*, brand: str, title: str, processor_line: str | None) -> CheckResult:
    """P1: product title includes brand name, processor line, or generation."""
    if brand not in tracked_brands():
        return CheckResult("P1", "product", None, "brand not tracked")

    passed, evidence = _title_names_brand(title, brand, processor_line)
    if passed:
        return CheckResult("P1", "product", True, evidence)
    if m := _GENERATION_RE.search(clean_text(title)):
        return CheckResult("P1", "product", True, f"generation:'{m.group(0)}'")
    return CheckResult("P1", "product", False, "no brand/line/generation token in title")


def check_p2(*, brand: str, badge_findings: list[BadgeFinding]) -> CheckResult:
    """P2: a brand badge is shown on the product page."""
    if brand not in tracked_brands():
        return CheckResult("P2", "product", None, "brand not tracked")
    if has_any_badge(badge_findings):
        shown = next(f.badge_name for f in badge_findings if f.is_present)
        return CheckResult("P2", "product", True, f"badge:'{shown}'")
    if not any(f.is_eligible for f in badge_findings):
        return CheckResult("P2", "product", None, "no eligible badge for this SKU")
    eligible = ", ".join(f.badge_name for f in badge_findings if f.is_eligible)
    return CheckResult("P2", "product", False, f"eligible but absent: {eligible}")


def check_p3(*, brand: str, specs: dict[str, str], processor_line: str | None) -> CheckResult:
    """P3: brand or processor line appears in the spec table."""
    if brand not in tracked_brands():
        return CheckResult("P3", "product", None, "brand not tracked")
    if not specs:
        return CheckResult("P3", "product", None, "spec table not found")
    display = brand_display_names().get(brand, brand)
    found, evidence = spec_mentions_brand_or_line(specs, display, processor_line)
    return CheckResult("P3", "product", found, evidence or "brand/line absent from specs")


def check_p4(*, brand: str, brand_media_text: str, page_loaded: bool) -> CheckResult:
    """P4: brand-led rich media present (images, HTML brand content)."""
    if brand not in tracked_brands():
        return CheckResult("P4", "product", None, "brand not tracked")
    if not page_loaded:
        return CheckResult("P4", "product", None, "product page not loaded")
    text = clean_text(brand_media_text)
    if not text:
        return CheckResult("P4", "product", False, "no brand rich-media block")
    display = brand_display_names().get(brand, brand).lower()
    if display in text.lower() or brand.lower() in text.lower():
        return CheckResult("P4", "product", True, f"brand media ({len(text)} chars)")
    return CheckResult("P4", "product", False, "rich media present but not brand-led")


def check_p5(*, brand: str, oem_media_present: bool, page_loaded: bool) -> CheckResult:
    """P5: OEM rich media present (images, videos, HTML content)."""
    if brand not in tracked_brands():
        return CheckResult("P5", "product", None, "brand not tracked")
    if not page_loaded:
        return CheckResult("P5", "product", None, "product page not loaded")
    return CheckResult(
        "P5", "product", oem_media_present,
        "OEM media block present" if oem_media_present else "no OEM media block",
    )


def unknown_product_checks(brand: str) -> list[CheckResult]:
    """P1-P5 when the product page could not be fetched at all."""
    reason = "product page not fetched"
    return [
        CheckResult(code, "product", None, reason) for code in ("P1", "P2", "P3", "P4", "P5")
    ]
