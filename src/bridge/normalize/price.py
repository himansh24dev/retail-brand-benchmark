"""Price and promotion parsing (module 1).

The hard part is that US and Brazilian conventions are mutually ambiguous:
"1.299" is one thousand two hundred ninety-nine in pt-BR and one point two
nine nine in en-US. Guessing from the string alone is unreliable, so parsing is
always driven by the platform's declared locale, with a separator-shape
heuristic only as a last resort.

Getting this wrong is not cosmetic: a BRL price parsed as USD convention turns
R$ 5.499,90 into 5.49, which would show up as a 99% price drop and fire a
false alert.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .text import clean_text

_DIGITS_RE = re.compile(r"[\d.,]+")
_PCT_RE = re.compile(r"(\d{1,3})\s*%")

# Promo language on both platforms, in both locales.
_PROMO_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bsave\b", r"\bdeal\b", r"\bpromo\b", r"\bcoupon\b", r"\bclearance\b",
        r"\brebate\b", r"\bdiscount\b", r"\boff\b", r"\bsale\b", r"\bshell\s*shocker\b",
        r"\bbundle\b", r"\blimited\s*time\b", r"\bflash\b",
        r"\bdesconto\b", r"\boferta\b", r"\bpromo[cç][aã]o\b", r"\bliquida[cç][aã]o\b",
        r"\bfrete\s*gr[aá]tis\b", r"\bcupom\b", r"\bà\s*vista\b", r"\bem\s*at[eé]\b",
    )
)

_OOS_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"out\s*of\s*stock", r"sold\s*out", r"unavailable", r"back\s*order",
        r"esgotado", r"indispon[ií]vel", r"sem\s*estoque",
    )
)


@dataclass(frozen=True)
class PriceInfo:
    price_current: float | None
    price_was: float | None
    currency: str
    discount_pct: float | None
    has_promo: bool
    promo_text: str | None


def parse_amount(raw: str | None, locale: str) -> float | None:
    """Parse a money string using the platform's locale convention.

    Returns None rather than 0.0 on failure — a missing price and a free
    product are different facts, and averaging zeros would silently drag every
    price metric down.
    """
    if not raw:
        return None
    text = clean_text(raw)
    match = _DIGITS_RE.search(text)
    if not match:
        return None
    token = match.group(0).strip(".,")
    if not token:
        return None

    decimal_comma = locale.lower().startswith("pt")

    if decimal_comma:
        # pt-BR: '.' groups thousands, ',' is the decimal point.
        normalised = token.replace(".", "").replace(",", ".")
    else:
        # en-US: ',' groups thousands, '.' is the decimal point.
        normalised = token.replace(",", "")

    # Guard against a locale/markup mismatch producing a nonsense value: if the
    # declared convention leaves multiple dots, the separators were the other
    # way round. Fall back to shape rather than returning a wrong number.
    if normalised.count(".") > 1:
        normalised = _parse_by_shape(token)

    try:
        value = float(normalised)
    except ValueError:
        return None
    return value if value > 0 else None


def _parse_by_shape(token: str) -> str:
    """Last-resort inference from separator layout alone.

    Whichever separator appears last is the decimal point, unless it is
    followed by exactly three digits and appears once, which is the unambiguous
    thousands-group shape.
    """
    last_dot, last_comma = token.rfind("."), token.rfind(",")
    if last_dot == last_comma == -1:
        return token
    sep_index = max(last_dot, last_comma)
    sep = token[sep_index]
    tail = token[sep_index + 1 :]
    if len(tail) == 3 and token.count(sep) == 1:
        return token.replace(sep, "")  # thousands group
    other = "," if sep == "." else "."
    return token.replace(other, "").replace(sep, ".")


def join_fraction_cents(fraction: str | None, cents: str | None, locale: str) -> float | None:
    """Rebuild a price from Mercado Libre's split fraction/cents markup.

    ML renders R$ 5.499,90 as separate '5.499' and '90' nodes. Parsing only the
    fraction node loses the cents; parsing them concatenated without the
    separator would produce 549990.
    """
    if not fraction:
        return None
    base = parse_amount(fraction, locale)
    if base is None:
        return None
    if cents and (digits := re.sub(r"\D", "", cents)):
        return base + int(digits[:2]) / 100
    return base


def detect_promo(
    promo_text: str | None,
    price_current: float | None,
    price_was: float | None,
) -> tuple[bool, float | None]:
    """Decide whether a listing is promoted, and by how much.

    Two independent signals: an explicit strike-through price, and promo copy.
    Either alone is enough — Newegg runs combo/coupon deals with no was-price,
    and ML shows a was-price with no promo text.
    """
    discount_pct: float | None = None
    if price_current and price_was and price_was > price_current:
        discount_pct = round((price_was - price_current) / price_was * 100, 2)

    text = clean_text(promo_text)
    has_text_promo = bool(text) and any(p.search(text) for p in _PROMO_PATTERNS)

    # A percentage in the promo copy is a usable discount when no was-price
    # was rendered.
    if discount_pct is None and text:
        if m := _PCT_RE.search(text):
            pct = float(m.group(1))
            if 0 < pct < 100:
                discount_pct = pct

    return bool(discount_pct) or has_text_promo, discount_pct


def build_price_info(
    *,
    price_current: float | None,
    price_was: float | None,
    currency: str,
    promo_text: str | None,
) -> PriceInfo:
    # A "was" price at or below current is markup noise, not a discount.
    if price_was is not None and price_current is not None and price_was <= price_current:
        price_was = None
    has_promo, discount_pct = detect_promo(promo_text, price_current, price_was)
    return PriceInfo(
        price_current=price_current,
        price_was=price_was,
        currency=currency,
        discount_pct=discount_pct,
        has_promo=has_promo,
        promo_text=clean_text(promo_text) or None,
    )


def parse_availability(raw: str | None) -> tuple[str | None, bool | None]:
    """Return (raw availability label, in_stock flag).

    in_stock is None when nothing was rendered — unknown is not the same as
    out of stock, and treating it as such would fire spurious stock alerts.
    """
    text = clean_text(raw)
    if not text:
        return None, None
    if any(p.search(text) for p in _OOS_PATTERNS):
        return text[:64], False
    return text[:64], True
