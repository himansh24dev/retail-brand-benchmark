"""Brand, OEM and product-type attribution."""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass

from ..config import (
    board_partner_pattern,
    brand_context_patterns,
    brand_fallback_patterns,
    oem_patterns,
    oem_sub_brand_patterns,
    processor_lines,
)
from .text import clean_text

SYSTEM_TYPES = frozenset({"notebook", "desktop", "workstation", "tablet"})
COMPONENT_TYPES = frozenset({"cpu", "gpu"})

CONF_LINE_IN_TITLE = 0.95
CONF_LINE_IN_SPECS = 0.85
CONF_BRAND_IN_TITLE = 0.60
CONF_BRAND_IN_SPECS = 0.45
CONF_NONE = 0.0

MIN_RELIABLE_CONFIDENCE = 0.60

_COMPONENT_HINTS = re.compile(
    r"\b(processador|processor|cpu|boxed|placa\s*de\s*v[ií]deo|graphics\s*card|"
    r"video\s*card|gpu|desktop\s*processor)\b",
    re.IGNORECASE,
)
_SYSTEM_HINTS = re.compile(
    r"\b(notebook|laptop|desktop|all[\s-]?in[\s-]?one|workstation|tablet|pc\b|"
    r"computador|macbook|imac|ipad)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class BrandAttribution:
    brand: str
    confidence: float
    processor_line: str | None = None
    processor_tier: str | None = None
    evidence: str | None = None

    @property
    def is_reliable(self) -> bool:
        return self.confidence >= MIN_RELIABLE_CONFIDENCE


@dataclass(frozen=True)
class OemAttribution:
    oem: str | None
    sub_brand: str | None = None
    evidence: str | None = None


def resolve_product_type(category_type: str | None, title: str) -> tuple[str, bool]:
    """Resolve product type, preferring the category we crawled it from."""
    title = clean_text(title)
    ctype = (category_type or "").strip().lower() or None

    if ctype in COMPONENT_TYPES:
        return ctype, True
    if ctype in SYSTEM_TYPES:
        if _COMPONENT_HINTS.search(title) and not _SYSTEM_HINTS.search(title):
            return ("gpu" if re.search(r"v[ií]deo|graphics|gpu|rtx|radeon\s*rx", title, re.I)
                    else "cpu"), True
        return ctype, False

    if _COMPONENT_HINTS.search(title) and not _SYSTEM_HINTS.search(title):
        return ("gpu" if re.search(r"v[ií]deo|graphics|gpu", title, re.I) else "cpu"), True
    for candidate, pattern in (
        ("notebook", r"\b(notebook|laptop|macbook)\b"),
        ("tablet", r"\b(tablet|ipad)\b"),
        ("workstation", r"\bworkstation\b"),
        ("desktop", r"\b(desktop|all[\s-]?in[\s-]?one|imac|computador|pc)\b"),
    ):
        if re.search(pattern, title, re.IGNORECASE):
            return candidate, False
    return "unknown", False


def attribute_brand(
    title: str,
    *,
    is_component: bool,
    spec_text: str = "",
    badge_text: str = "",
) -> BrandAttribution:
    """Attribute a SKU to its chip/SoC supplier."""
    title_text = clean_text(title)
    secondary = clean_text(f"{spec_text} {badge_text}")

    for source, text, confidence in (
        ("title", title_text, CONF_LINE_IN_TITLE),
        ("specs", secondary, CONF_LINE_IN_SPECS),
    ):
        if not text:
            continue
        for line in processor_lines():
            if line.discrete_gpu and not is_component:
                continue
            if not _has_context(line.brand, f"{title_text} {secondary}"):
                continue
            for pattern in line.patterns:
                if m := pattern.search(text):
                    return BrandAttribution(
                        brand=line.brand,
                        confidence=confidence,
                        processor_line=line.name,
                        processor_tier=line.tier,
                        evidence=f"{source}:'{m.group(0)}'",
                    )

    for source, text, confidence in (
        ("title", title_text, CONF_BRAND_IN_TITLE),
        ("specs", secondary, CONF_BRAND_IN_SPECS),
    ):
        if not text:
            continue
        for brand_key, patterns in brand_fallback_patterns():
            if not is_component and not _supplies_system_silicon(brand_key):
                continue
            if not _has_context(brand_key, f"{title_text} {secondary}"):
                continue
            for pattern in patterns:
                if m := pattern.search(text):
                    return BrandAttribution(
                        brand=brand_key,
                        confidence=confidence,
                        evidence=f"{source}:'{m.group(0)}'",
                    )

    return BrandAttribution(brand="other", confidence=CONF_NONE, evidence=None)


@functools.lru_cache(maxsize=None)
def _supplies_system_silicon(brand_key: str) -> bool:
    """Whether this brand ships a CPU/SoC that can power a whole system."""
    return any(
        line.brand == brand_key and not line.discrete_gpu for line in processor_lines()
    )


def _has_context(brand_key: str, text: str) -> bool:
    """Enforce the corroborating-context requirement for collision-prone brands."""
    required = brand_context_patterns().get(brand_key)
    if not required:
        return True
    return any(p.search(text) for p in required)


def attribute_oem(
    title: str,
    *,
    is_component: bool,
    brand_field: str = "",
    spec_text: str = "",
) -> OemAttribution:
    """Attribute the device maker."""
    if is_component:
        return OemAttribution(oem=None, evidence="component:no-oem")

    haystack = clean_text(f"{brand_field} {title} {spec_text}")
    if not haystack:
        return OemAttribution(oem="unknown")

    brand_field_text = clean_text(brand_field)
    if brand_field_text:
        for oem_key, patterns in oem_patterns():
            for pattern in patterns:
                if m := pattern.search(brand_field_text):
                    return OemAttribution(
                        oem=oem_key,
                        sub_brand=_sub_brand(oem_key, haystack),
                        evidence=f"brand_field:'{m.group(0)}'",
                    )

    for oem_key, patterns in oem_patterns():
        for pattern in patterns:
            if m := pattern.search(haystack):
                return OemAttribution(
                    oem=oem_key,
                    sub_brand=_sub_brand(oem_key, haystack),
                    evidence=f"title:'{m.group(0)}'",
                )

    if m := board_partner_pattern().search(haystack):
        return OemAttribution(oem=None, evidence=f"board_partner:'{m.group(0)}'")

    return OemAttribution(oem="unknown")


def _sub_brand(oem_key: str, haystack: str) -> str | None:
    for candidate_oem, sub_name, pattern in oem_sub_brand_patterns():
        if candidate_oem == oem_key and pattern.search(haystack):
            return sub_name
    return None
