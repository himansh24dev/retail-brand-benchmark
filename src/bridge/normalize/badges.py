"""Badge detection and eligibility (module 6)."""

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
        """Present but not eligible — e.g. an Evo badge on a desktop."""
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
    """Evaluate every badge belonging to `brand` against one page."""
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
    """Remove `needle` from `haystack` so it cannot be matched against."""
    if not needle or not haystack:
        return haystack
    out = haystack.replace(needle, " ")
    if out != haystack:
        return out
    tokens = [t for t in needle.split() if len(t) > 2]
    for token in tokens:
        out = out.replace(token, " ")
    return out


def has_any_badge(findings: list[BadgeFinding]) -> bool:
    """Whether any brand badge was rendered — the S2/P2 rubric signal."""
    return any(f.is_present for f in findings)
