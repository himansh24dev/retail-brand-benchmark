"""Selector-chain resolution over scraped HTML.

Config expresses selectors as ordered fallback chains with an optional
attribute suffix:

    title: ['a.item-title', '.item-info .item-title']
    url:   ['a.item-title@href']
    image: ['img@src', 'img@data-src']

The chain is the point. Retail DOMs change without warning and usually in one
place at a time; a chain survives a single rename where a lone selector returns
None and silently zeroes out a metric. `MissTracker` records which selectors are
returning nothing so drift is visible in the run summary rather than showing up
a week later as an unexplained gap in a chart.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from selectolax.parser import HTMLParser, Node

from ..normalize.text import clean_text


@dataclass
class MissTracker:
    """Counts selector chains that resolved to nothing.

    A chain missing on one card is normal (not every product has a promo). A
    chain missing on *every* card means the markup moved, which is a different
    problem and needs to be loud.
    """

    attempts: Counter[str] = field(default_factory=Counter)
    misses: Counter[str] = field(default_factory=Counter)

    def record(self, field_name: str, hit: bool) -> None:
        self.attempts[field_name] += 1
        if not hit:
            self.misses[field_name] += 1

    def drifted_fields(self, threshold: float = 0.95) -> list[tuple[str, int, int]]:
        """Fields missing on nearly every element — probable selector drift."""
        out = []
        for name, attempted in self.attempts.items():
            missed = self.misses.get(name, 0)
            if attempted >= 5 and missed / attempted >= threshold:
                out.append((name, missed, attempted))
        return sorted(out, key=lambda r: -r[1])

    def summary(self) -> str:
        drifted = self.drifted_fields()
        if not drifted:
            return "no selector drift detected"
        return "possible selector drift: " + ", ".join(
            f"{name} ({missed}/{attempted} missing)" for name, missed, attempted in drifted
        )


def parse_html(html: str) -> HTMLParser:
    return HTMLParser(html)


def _split_selector(selector: str) -> tuple[str, str | None]:
    """Split 'a.item-title@href' into ('a.item-title', 'href').

    A bare '@href' means "the attribute of the element itself", used when the
    container node already is the anchor.
    """
    if "@" not in selector:
        return selector, None
    css, _, attr = selector.rpartition("@")
    return (css or ""), (attr or None)


def select_one(
    root: Node | HTMLParser,
    chain: list[str] | tuple[str, ...] | None,
    *,
    field_name: str | None = None,
    tracker: MissTracker | None = None,
) -> str | None:
    """Resolve the first selector in the chain that yields a non-empty value."""
    value: str | None = None
    for selector in chain or ():
        css, attr = _split_selector(selector)
        node = root if not css else root.css_first(css)
        if node is None:
            continue
        raw = node.attributes.get(attr) if attr else node.text()
        if cleaned := clean_text(raw):
            value = cleaned
            break

    if tracker is not None and field_name:
        tracker.record(field_name, value is not None)
    return value


def select_all(root: Node | HTMLParser, chain: list[str] | tuple[str, ...] | None) -> list[Node]:
    """Return nodes from the first selector in the chain that matches anything."""
    for selector in chain or ():
        css, _ = _split_selector(selector)
        if not css:
            continue
        if nodes := root.css(css):
            return nodes
    return []


def select_texts(root: Node | HTMLParser, chain: list[str] | tuple[str, ...] | None) -> list[str]:
    """Collect every value a chain matches, across all matching selectors.

    Unlike `select_one`, this does not stop at the first matching selector:
    badges appear in several places on a page and the union is what the rubric
    needs.
    """
    out: list[str] = []
    for selector in chain or ():
        css, attr = _split_selector(selector)
        nodes = root.css(css) if css else [root]
        for node in nodes:
            raw = node.attributes.get(attr) if attr else node.text()
            if cleaned := clean_text(raw):
                out.append(cleaned)
    # Order-preserving dedupe; the first occurrence is usually the most
    # prominent placement, which matters for "prominently displayed".
    return list(dict.fromkeys(out))


def extract_spec_table(root: Node | HTMLParser, chain: list[str] | tuple[str, ...] | None) -> dict[str, str]:
    """Pull label/value pairs from a spec table.

    Handles both shapes retailers use: two-cell rows (<th>label</th><td>value</td>)
    and definition-list markup. Rows that do not resolve to exactly one label
    and one value are skipped rather than guessed at.
    """
    specs: dict[str, str] = {}
    for table in select_all(root, chain):
        for row in table.css("tr"):
            cells = row.css("th, td")
            if len(cells) < 2:
                continue
            key = clean_text(cells[0].text())
            value = clean_text(cells[1].text())
            if key and value and key.lower() != value.lower():
                specs.setdefault(key, value)

        # Definition-list variant (Mercado Libre uses this on some categories).
        terms, definitions = table.css("dt"), table.css("dd")
        if terms and len(terms) == len(definitions):
            for term, definition in zip(terms, definitions):
                key, value = clean_text(term.text()), clean_text(definition.text())
                if key and value:
                    specs.setdefault(key, value)
    return specs


def node_text(root: Node | HTMLParser) -> str:
    """Full visible text of a subtree, for weak-signal fallback matching."""
    try:
        return clean_text(root.text())
    except Exception:
        return ""


def absolute_url(base_url: str, href: str | None) -> str | None:
    if not href:
        return None
    href = href.strip()
    if href.startswith(("http://", "https://")):
        return href
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return base_url.rstrip("/") + href
    return None
