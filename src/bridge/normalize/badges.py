"""Badge detection and eligibility (module 6).

The brief asks not just whether badges are present, but "whether they're
correctly and prominently displayed where relevant". That word does the work:
a missing Intel Evo badge on a desktop is not a finding, because Evo is a
laptop-only certification. So detection alone is insufficient — every badge is
evaluated as a pair:

    eligible  = this SKU's processor line and product type qualify for it
    present   = it was actually rendered on the page

A compliance gap is eligible AND NOT present. Reporting raw presence counts
would bury real gaps under badges that never applied in the first place.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import badge_specs
from .text import clean_text


@dataclass(frozen=True)
class BadgeFinding:
    brand: str
    badge_name: str
    page_type: str
    is_eligible: bool
    is_present: bool
    evidence: str | None = None

    @property
    def is_compliance_gap(self) -> bool:
        return self.is_eligible and not self.is_present

    @property
    def is_misapplied(self) -> bool:
        """Present but not eligible — e.g. an Evo badge on a desktop.

        Rarer than a gap, and a different conversation with the retailer, so
        it is tracked separately rather than folded into the gap count.
        """
        return self.is_present and not self.is_eligible


def detect_badges(
    *,
    brand: str,
    processor_line: str | None,
    product_type: str | None,
    page_type: str,
    badge_text: str = "",
    page_text: str = "",
    exclude_text: str = "",
) -> list[BadgeFinding]:
    """Evaluate every badge belonging to `brand` against one page.

    Only the attributed brand's badges are evaluated. Checking AMD's badges on
    an Intel laptop would generate noise: they are correctly absent.

    `badge_text` is the high-confidence surface (badge image alt attributes,
    dedicated badge elements); `page_text` is the broader page body, used as a
    weaker fallback so a badge rendered as text rather than an image still
    counts as present.

    `exclude_text` must be the product title. A title reading "Lenovo Legion,
    AMD Ryzen 7" contains the literal string the AMD Ryzen badge pattern
    matches, so without this the title alone marks the badge present. That
    would make S2 a copy of S1 and P2 a copy of P1 — the badge checks would
    report ~100% compliance and detect nothing. Badge presence has to come from
    badge markup, not from the title restating the processor.
    """
    badge_blob = clean_text(badge_text)
    page_blob = _strip_occurrences(clean_text(page_text), clean_text(exclude_text))
    findings: list[BadgeFinding] = []

    for spec in badge_specs():
        if spec.brand != brand:
            continue

        eligible = spec.is_eligible(processor_line, product_type)
        present = False
        evidence: str | None = None

        for pattern in spec.patterns:
            if m := pattern.search(badge_blob):
                present, evidence = True, f"badge_element:'{m.group(0)}'"
                break
        if not present:
            for pattern in spec.patterns:
                if m := pattern.search(page_blob):
                    present, evidence = True, f"page_text:'{m.group(0)}'"
                    break

        # Skip the vast uninteresting middle: not eligible and not present is
        # the correct state for most badge/SKU pairs and would otherwise
        # dominate the table.
        if not eligible and not present:
            continue

        findings.append(
            BadgeFinding(
                brand=spec.brand,
                badge_name=spec.name,
                page_type=page_type,
                is_eligible=eligible,
                is_present=present,
                evidence=evidence,
            )
        )

    return findings


def _strip_occurrences(haystack: str, needle: str) -> str:
    """Remove `needle` from `haystack` so it cannot be matched against.

    Falls back to word-level removal when the exact title string is not present
    verbatim — listing and product pages often render the same title with
    different whitespace or truncation.
    """
    if not needle or not haystack:
        return haystack
    out = haystack.replace(needle, " ")
    if out != haystack:
        return out
    # Title not present verbatim: drop its distinctive tokens instead.
    tokens = [t for t in needle.split() if len(t) > 2]
    for token in tokens:
        out = out.replace(token, " ")
    return out


def has_any_badge(findings: list[BadgeFinding]) -> bool:
    """Whether any brand badge was rendered — the S2/P2 rubric signal."""
    return any(f.is_present for f in findings)
