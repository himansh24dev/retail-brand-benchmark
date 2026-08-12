"""Shared text utilities for attribution and parsing."""

from __future__ import annotations

import html
import re
import unicodedata

_WHITESPACE_RE = re.compile(r"\s+")
_TAG_RE = re.compile(r"<[^>]+>")


def clean_text(value: str | None) -> str:
    """Collapse a scraped string into comparable plain text.

    Retail markup arrives with entities, non-breaking spaces and stray tags
    inside text nodes. Normalising here means every downstream regex sees one
    consistent shape rather than each caller re-solving it.
    """
    if not value:
        return ""
    text = html.unescape(value)
    text = _TAG_RE.sub(" ", text)
    # NFKC folds the full-width and non-breaking variants retail sites emit
    # (e.g. NBSP inside prices) onto their ASCII equivalents.
    text = unicodedata.normalize("NFKC", text)
    text = text.replace(" ", " ")
    return _WHITESPACE_RE.sub(" ", text).strip()


def strip_accents(value: str) -> str:
    """Drop diacritics — needed for pt-BR spec keys ('Memória' -> 'Memoria')."""
    decomposed = unicodedata.normalize("NFD", value)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def normalize_key(value: str) -> str:
    """Fold a spec label into a stable lookup key."""
    return re.sub(r"[^a-z0-9]+", "_", strip_accents(clean_text(value)).lower()).strip("_")


def first_match(patterns, text: str) -> str | None:
    """Return the matched substring of the first pattern that hits."""
    for pattern in patterns:
        if m := pattern.search(text):
            return m.group(0)
    return None


def any_match(patterns, text: str) -> bool:
    return any(p.search(text) for p in patterns)
