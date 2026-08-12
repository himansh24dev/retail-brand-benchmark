"""Render the catalogue into platform-shaped HTML fixtures.

The markup mirrors each platform's real DOM closely enough that the production
selector chains in config/platforms.yaml resolve against it unchanged. That is
the point: the parsers under test are the parsers that will run live, so a
selector bug shows up here rather than on the first day of real collection.

Variants model successive collection runs. Drift is deterministic (seeded per
SKU per variant) so the same variant always renders identically — a run can be
re-executed and reproduce its numbers exactly, which matters when explaining a
chart in a walkthrough.

Drift is applied to the *rendered HTML*, never to computed metrics. Every
number downstream is derived by the real pipeline from these pages.
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from catalog import BADGE_RATE, BRAND_MEDIA_RATE, CatalogItem, catalog_for  # noqa: E402

FIXTURE_ROOT = Path(__file__).resolve().parent


def visible_specs(item: CatalogItem, drift: "Drift") -> dict[str, str]:
    """The spec rows a page actually renders.

    Drops the processor/brand rows when this SKU is drifted non-compliant, so
    P3 has real failures to find.
    """
    if drift.spec_lists_processor:
        return item.specs
    hidden = {"processor", "processador", "brand", "marca"}
    return {k: v for k, v in item.specs.items() if k.strip().lower() not in hidden}


def _rng(*parts: object) -> random.Random:
    """Deterministic RNG keyed by its inputs, so drift is reproducible."""
    seed = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:16]
    return random.Random(int(seed, 16))


# ---------------------------------------------------------------------------
# Drift: what changes between collection runs
# ---------------------------------------------------------------------------


class Drift:
    """Per-SKU, per-variant state changes."""

    def __init__(self, item: CatalogItem, variant: int, platform: str):
        rng = _rng(platform, item.sku, variant)
        self.variant = variant

        # Price random walk. Bounded so a week of drift stays plausible;
        # a few SKUs get a deliberate sharp cut to exercise price-drop alerts.
        drift_pct = rng.gauss(0, 2.2)
        if rng.random() < 0.06:
            drift_pct -= rng.uniform(9, 22)     # flash sale
        drift_pct = max(-35.0, min(18.0, drift_pct))
        self.price = round(item.base_price_usd * (1 + drift_pct / 100), 2)

        # Promotions come and go independently of price.
        self.on_promo = rng.random() < 0.34
        self.discount_pct = round(rng.uniform(6, 28)) if self.on_promo else 0
        self.price_was = (
            round(self.price / (1 - self.discount_pct / 100), 2) if self.on_promo else None
        )

        # Badge presence: base rate per brand, with occasional loss so
        # badge_disappeared alerts have something real to fire on.
        base_rate = BADGE_RATE.get(item.brand, 0.5)
        self.badge_present = bool(item.badge_alt) and rng.random() < base_rate

        media_rate = BRAND_MEDIA_RATE.get(item.brand, 0.4)
        self.brand_media = item.has_brand_media and rng.random() < media_rate
        self.oem_media = item.has_oem_media and rng.random() < 0.72

        self.in_stock = rng.random() > 0.05
        self.rating = round(rng.uniform(3.6, 4.9), 1)
        self.reviews = rng.randint(3, 890)
        self.sponsored = rng.random() < 0.10
        # Rank jitter drives share-of-shelf and SoV movement between runs.
        self.rank_jitter = rng.uniform(-1, 1)

        # Title compliance (rubric S1/P1): a minority of listings omit the
        # processor from the title entirely, which is a genuine retail failure
        # mode and the thing S1 exists to catch.
        self.title_has_processor = rng.random() < 0.82

        # Spec-table compliance (rubric P3). Retailers routinely publish a
        # spec table that lists RAM and storage but never names the silicon.
        # Without this the fixture set would render P3 at a flat 100% and the
        # check would demonstrate nothing.
        self.spec_lists_processor = rng.random() < 0.80


def ordered_items(items: list[CatalogItem], variant: int, platform: str) -> list[CatalogItem]:
    """Shelf order for a run — stable base order plus per-run jitter."""
    scored = []
    for index, item in enumerate(items):
        drift = Drift(item, variant, platform)
        scored.append((index + drift.rank_jitter * 2.5, item))
    return [item for _, item in sorted(scored, key=lambda pair: pair[0])]


def strip_processor(title: str, item: CatalogItem) -> str:
    """Produce a non-compliant title by removing the processor mention."""
    proc = item.specs.get("Processor") or item.specs.get("Processador") or ""
    out = title
    for token in proc.split():
        if len(token) > 2:
            out = out.replace(token, "")
    return " ".join(out.split()) or title


# ---------------------------------------------------------------------------
# Newegg rendering
# ---------------------------------------------------------------------------


def _usd(value: float) -> tuple[str, str]:
    whole, cents = f"{value:,.2f}".split(".")
    return whole, cents


def newegg_listing_cell(item: CatalogItem, drift: Drift, rank: int) -> str:
    whole, cents = _usd(drift.price)
    title = item.title if drift.title_has_processor else strip_processor(item.title, item)

    was_html = ""
    if drift.price_was:
        w_whole, w_cents = _usd(drift.price_was)
        was_html = f'<li class="price-was">${w_whole}.{w_cents}</li>'

    promo_html = ""
    if drift.on_promo:
        promo_html = f'<p class="item-promo">Save {drift.discount_pct}% with promo code</p>'

    badge_html = ""
    if drift.badge_present and item.badge_alt:
        badge_html = (
            f'<a class="item-brand"><img src="/badge.png" alt="{item.badge_alt}" '
            f'title="{item.badge_alt}" /></a>'
        )

    sponsored_html = '<span class="txt-ads-flag">Sponsored</span>' if drift.sponsored else ""
    features = "".join(f"<li>{k}: {v}</li>" for k, v in list(item.specs.items())[:4])

    return f"""
    <div class="item-cell" data-rank="{rank}">
      <div class="item-container">
        <a class="item-img" href="/p/{item.sku}"><img src="/img/{item.sku}.jpg" alt="{title[:60]}"/></a>
        <div class="item-info">
          <a class="item-title" href="https://www.newegg.com/p/{item.sku}">{title}</a>
          <div class="item-branding">{badge_html}
            <a class="item-rating" title="Rating + {int(drift.rating)}"><span class="item-rating-num">({drift.reviews})</span></a>
          </div>
          <ul class="item-features">{features}</ul>
          {sponsored_html}
          {promo_html}
          <div class="item-action">
            <ul class="price">
              {was_html}
              <li class="price-current"><strong>{whole}</strong><sup>.{cents}</sup></li>
            </ul>
          </div>
        </div>
      </div>
    </div>"""


def newegg_listing_page(items: list[CatalogItem], variant: int, page: int, category: str) -> str:
    cells = []
    for offset, item in enumerate(items):
        drift = Drift(item, variant, "newegg_us")
        cells.append(newegg_listing_cell(item, drift, rank=offset + 1))
    return f"""<!DOCTYPE html>
<html lang="en-us"><head><meta charset="utf-8"/>
<title>{category} - Newegg.com</title></head>
<body>
<div class="page-content">
  <div class="list-wrap"><div class="item-cells-wrap">
    {''.join(cells)}
  </div></div>
  <div class="list-tool-pagination"><span>Page {page}</span></div>
</div>
</body></html>"""


def newegg_product_page(item: CatalogItem, variant: int) -> str:
    drift = Drift(item, variant, "newegg_us")
    whole, cents = _usd(drift.price)
    title = item.title if drift.title_has_processor else strip_processor(item.title, item)

    was_html = ""
    discount_html = ""
    if drift.price_was:
        w_whole, w_cents = _usd(drift.price_was)
        was_html = f'<li class="price-was">${w_whole}.{w_cents}</li>'
        saved = drift.price_was - drift.price
        discount_html = (
            f'<div class="product-price-discount">Save: ${saved:,.2f} '
            f'({drift.discount_pct}%)</div>'
        )

    badge_html = ""
    if drift.badge_present and item.badge_alt:
        badge_html = (
            f'<div class="product-badges"><img src="/badge.png" alt="{item.badge_alt}"/></div>'
        )

    # P4: brand-led rich media
    brand_media = ""
    if drift.brand_media and item.brand not in ("other", "nvidia", "mediatek"):
        brand_media = f"""
        <div class="product-manufacturer-content">
          <h2>{item.badge_alt or item.brand.title()}</h2>
          <img src="/brand/{item.brand}-hero.jpg" alt="{item.brand.title()} technology"/>
          <p>Engineered for gaming performance with {item.specs.get('Processor', 'the latest silicon')}.</p>
        </div>"""

    # P5: OEM rich media
    oem_media = ""
    if drift.oem_media:
        oem_media = """
        <div class="product-overview-img">
          <img src="/oem/gallery-1.jpg" alt="Product gallery"/>
          <video src="/oem/overview.mp4"></video>
        </div>"""

    rows = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in visible_specs(item, drift).items())
    stock = "In stock." if drift.in_stock else "Out of Stock"
    oem_field = item.oem.title() if item.oem else (item.specs.get("Brand", ""))

    return f"""<!DOCTYPE html>
<html lang="en-us"><head><meta charset="utf-8"/><title>{title} - Newegg.com</title></head>
<body>
<div class="product-wrap">
  <h1 class="product-title">{title}</h1>
  <div class="product-brand"><a title="{oem_field}"><img src="/oem.png" alt="{oem_field}"/></a></div>
  {badge_html}
  <div class="product-buy">
    <ul class="price">{was_html}
      <li class="price-current"><strong>{whole}</strong><sup>.{cents}</sup></li>
    </ul>
    {discount_html}
    <div class="product-inventory">{stock}</div>
  </div>
  <div id="product-details">
    <table class="table-horizontal"><tbody>{rows}</tbody></table>
    {brand_media}
    {oem_media}
  </div>
</div>
</body></html>"""


# ---------------------------------------------------------------------------
# Mercado Libre rendering
# ---------------------------------------------------------------------------


def _brl(value: float) -> tuple[str, str]:
    whole, cents = f"{value:,.2f}".split(".")
    # pt-BR: '.' groups thousands, ',' is the decimal separator.
    return whole.replace(",", "."), cents


def ml_listing_card(item: CatalogItem, drift: Drift, rank: int) -> str:
    whole, cents = _brl(drift.price)
    title = item.title if drift.title_has_processor else strip_processor(item.title, item)

    was_html = ""
    if drift.price_was:
        w_whole, _ = _brl(drift.price_was)
        was_html = (
            '<s class="andes-money-amount andes-money-amount--previous">'
            f'<span class="andes-money-amount__fraction">{w_whole}</span></s>'
        )

    disc_html = ""
    if drift.on_promo:
        disc_html = f'<span class="andes-money-amount__discount">{drift.discount_pct}% OFF</span>'

    badge_html = ""
    if drift.badge_present and item.badge_alt:
        badge_html = f'<span class="poly-component__highlight">{item.badge_alt}</span>'

    sponsored = '<span class="poly-component__ads-promotions">Patrocinado</span>' if drift.sponsored else ""

    return f"""
    <div class="poly-card poly-card--grid-card" data-rank="{rank}">
      <div class="poly-card__portada">
        <img class="poly-component__picture" src="/img/{item.sku}.webp" alt="{title[:60]}"/>
      </div>
      <div class="poly-card__content">
        <h3 class="poly-component__title-wrapper">
          <a class="poly-component__title" href="https://produto.mercadolivre.com.br/{item.sku}">{title}</a>
        </h3>
        <div class="poly-component__price">
          {was_html}
          <div class="poly-price__current">
            <span class="andes-money-amount">
              <span class="andes-money-amount__fraction">{whole}</span>
              <span class="andes-money-amount__cents">{cents}</span>
            </span>
            {disc_html}
          </div>
        </div>
        {badge_html}
        {sponsored}
        <div class="poly-reviews__rating">{drift.rating}</div>
      </div>
    </div>"""


def ml_listing_page(items: list[CatalogItem], variant: int, offset: int, category: str) -> str:
    cards = []
    for index, item in enumerate(items):
        drift = Drift(item, variant, "mercadolibre_br")
        cards.append(ml_listing_card(item, drift, rank=offset + index + 1))
    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8"/>
<title>{category} | Mercado Livre</title></head>
<body>
<section class="ui-search-results">
  {''.join(cards)}
</section>
</body></html>"""


def ml_product_page(item: CatalogItem, variant: int) -> str:
    drift = Drift(item, variant, "mercadolibre_br")
    whole, cents = _brl(drift.price)
    title = item.title if drift.title_has_processor else strip_processor(item.title, item)

    was_html = ""
    if drift.price_was:
        w_whole, _ = _brl(drift.price_was)
        was_html = (
            '<span class="ui-pdp-price__original-value">'
            f'<span class="andes-money-amount__fraction">{w_whole}</span></span>'
        )
    disc_html = (
        f'<span class="andes-money-amount__discount">{drift.discount_pct}% OFF</span>'
        if drift.on_promo else ""
    )

    badge_html = ""
    if drift.badge_present and item.badge_alt:
        badge_html = f'<div class="ui-pdp-highlighted-specs__attribute">{item.badge_alt}</div>'

    brand_media = ""
    if drift.brand_media and item.brand not in ("other", "nvidia", "mediatek"):
        brand_media = f"""
        <div class="ui-pdp-description__content">
          <h2>{item.badge_alt or item.brand.title()}</h2>
          <p>Desempenho de ponta com {item.specs.get('Processador', 'a mais recente tecnologia')}.</p>
          <img src="/brand/{item.brand}.jpg" alt="{item.brand.title()}"/>
        </div>"""

    oem_media = ""
    if drift.oem_media:
        oem_media = """
        <div class="ui-pdp-gallery">
          <img src="/gallery/1.webp" alt="Galeria"/>
          <video src="/gallery/overview.mp4"></video>
        </div>"""

    rows = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in visible_specs(item, drift).items())
    stock = "Estoque disponível" if drift.in_stock else "Sem estoque"
    seller = item.oem.title() if item.oem else item.specs.get("Marca", "Loja oficial")

    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8"/><title>{title} | Mercado Livre</title></head>
<body>
<div class="ui-pdp-container">
  <h1 class="ui-pdp-title">{title}</h1>
  <div class="ui-pdp-price__second-line">
    {was_html}
    <span class="andes-money-amount__fraction">{whole}</span>
    <span class="andes-money-amount__cents">{cents}</span>
    {disc_html}
  </div>
  {badge_html}
  <div class="ui-pdp-stock-information">{stock}</div>
  <div class="ui-pdp-official-store">{seller}</div>
  <table class="andes-table"><tbody>{rows}</tbody></table>
  {brand_media}
  {oem_media}
</div>
</body></html>"""


# ---------------------------------------------------------------------------
# Homepage banners (module 3)
# ---------------------------------------------------------------------------

# Banner rotation per variant. Brand share here is deliberately uneven and
# shifts across runs, so banner-share trend has something real to show.
_BANNER_POOL = {
    "newegg_us": [
        ("Intel Core Ultra Powered Laptops - Save up to $400", "/promotions/intel-core-ultra", "Intel Core Ultra"),
        ("AMD Ryzen Gaming Week - Up to 25% Off", "/promotions/amd-ryzen-week", "AMD Ryzen"),
        ("Shop MacBook Pro with M4", "/promotions/apple-macbook", "Apple Silicon"),
        ("Snapdragon X Elite Copilot+ PCs", "/promotions/snapdragon-copilot", "Snapdragon"),
        ("GeForce RTX 40 Series Deals", "/promotions/geforce-rtx", "GeForce RTX"),
        ("Build Your Dream PC - Component Sale", "/promotions/pc-builder", None),
        ("Intel Evo Certified Thin & Light", "/promotions/intel-evo", "Intel Evo"),
    ],
    "mercadolibre_br": [
        ("Notebooks Gamer AMD Ryzen - Ofertas da Semana", "/ofertas/amd-ryzen", "AMD Ryzen"),
        ("Intel Core i7 - Até 30% OFF", "/ofertas/intel-core", "Intel Core i7"),
        ("MacBook com Chip M4 - Frete Grátis", "/ofertas/apple-macbook", "Apple Silicon"),
        ("Placas de Vídeo RTX - Melhores Preços", "/ofertas/placas-video", "GeForce RTX"),
        ("Semana do Consumidor - PC Gamer", "/ofertas/pc-gamer", None),
        ("Notebooks Snapdragon Copilot+", "/ofertas/snapdragon", "Snapdragon"),
    ],
}


def homepage(platform: str, variant: int, items: list[CatalogItem]) -> str:
    pool = _BANNER_POOL[platform]
    rng = _rng(platform, "banner", variant)
    count = rng.randint(4, min(6, len(pool)))
    chosen = rng.sample(pool, count)

    # Featured-product tiles, distinct from the carousel. Module 8 asks for
    # brand presence on the home page as well as on search pages, and a
    # carousel-only homepage would leave that path with nothing to parse.
    # The selection is reseeded per variant so the brand mix moves run to run,
    # which is what makes homepage presence a trend rather than a constant.
    feat_rng = _rng(platform, "featured", variant)
    featured = feat_rng.sample(items, min(8, len(items)))

    # Each platform gets its own carousel markup. Rendering one shape for both
    # would leave the other platform's selector chain permanently untested,
    # which is exactly the bug this fixture set exists to catch early.
    if platform == "mercadolibre_br":
        slides = "".join(
            f"""
      <div class="andes-carousel-snapped__slide">
        <a href="{href}"><img src="/banner/{i}.jpg" alt="{alt}" title="{alt}"/></a>
      </div>"""
            for i, (alt, href, _b) in enumerate(chosen, start=1)
        )
        cards = "".join(
            ml_listing_card(item, Drift(item, variant, platform), rank=i)
            for i, item in enumerate(featured, start=1)
        )
        return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8"/><title>Mercado Livre</title></head>
<body>
<div class="andes-carousel-snapped">{slides}</div>
<section class="ui-recommendations-list">{cards}</section>
</body></html>"""

    slides = "".join(
        f"""
      <div class="swiper-slide">
        <a class="main-banner-item" href="{href}">
          <img src="/banner/{i}.jpg" alt="{alt}" title="{alt}"/>
        </a>
      </div>"""
        for i, (alt, href, _b) in enumerate(chosen, start=1)
    )
    cells = "".join(
        newegg_listing_cell(item, Drift(item, variant, platform), rank=i)
        for i, item in enumerate(featured, start=1)
    )
    return f"""<!DOCTYPE html>
<html lang="en-us"><head><meta charset="utf-8"/><title>Newegg.com</title></head>
<body>
<div class="main-banner">
  <div class="swiper-wrapper">{slides}</div>
</div>
<div class="homepage-deals">
  <div class="item-cells-wrap">{cells}</div>
</div>
</body></html>"""


# ---------------------------------------------------------------------------
# Search results (module 8)
# ---------------------------------------------------------------------------


def search_page(platform: str, keyword: str, variant: int, items: list[CatalogItem]) -> str:
    """Rank the catalogue for a keyword.

    Relevance is a crude token-overlap score plus per-run jitter — enough to
    give each brand a defensible, moving rank distribution without pretending
    to model a real search engine.
    """
    rng = _rng(platform, keyword, variant)
    tokens = {t for t in keyword.lower().split() if len(t) > 2}

    scored = []
    for item in items:
        title_tokens = set(item.title.lower().split())
        overlap = len(tokens & title_tokens)
        type_bonus = 2.0 if any(t in item.title.lower() for t in tokens) else 0.0
        score = overlap * 3 + type_bonus + rng.uniform(0, 4)
        scored.append((score, item))

    ranked = [item for _, item in sorted(scored, key=lambda pair: -pair[0])][:40]

    if platform == "mercadolibre_br":
        cards = [
            ml_listing_card(item, Drift(item, variant, platform), rank=index + 1)
            for index, item in enumerate(ranked)
        ]
        return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8"/><title>{keyword} | Mercado Livre</title></head>
<body><section class="ui-search-results">{''.join(cards)}</section></body></html>"""

    cells = [
        newegg_listing_cell(item, Drift(item, variant, platform), rank=index + 1)
        for index, item in enumerate(ranked)
    ]
    return f"""<!DOCTYPE html>
<html lang="en-us"><head><meta charset="utf-8"/><title>{keyword} - Newegg.com</title></head>
<body><div class="item-cells-wrap">{''.join(cells)}</div></body></html>"""


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def generate(variants: int = 9) -> None:
    """Write the full fixture set.

    Nine variants ~= three days at the brief's 3x-daily cadence, which is
    enough for trends, alerts and slot-over-slot comparison to be meaningful.
    """
    sys.path.insert(0, str(FIXTURE_ROOT.parents[1] / "src"))
    from bridge.config import keywords_config, platforms_config

    platforms = platforms_config()["platforms"]
    total_files = 0

    for platform_key, pcfg in platforms.items():
        root = FIXTURE_ROOT / platform_key
        root.mkdir(parents=True, exist_ok=True)
        items = catalog_for(platform_key)
        index: dict[str, str] = {}

        page_size = 24 if platform_key == "newegg_us" else 50

        for variant in range(variants):
            suffix = "" if variant == 0 else f".v{variant}"

            # --- category listings
            for category in pcfg["listing"]["categories"]:
                ctype = category["product_type"]
                pool = [i for i in items if i.product_type == ctype]
                if not pool:
                    continue
                ordered = ordered_items(pool, variant, platform_key)

                for page_num in range(1, max(1, -(-len(ordered) // page_size)) + 1):
                    chunk = ordered[(page_num - 1) * page_size : page_num * page_size]
                    if platform_key == "newegg_us":
                        url = category["url"] if page_num == 1 else f"{category['url']}?page={page_num}"
                        html = newegg_listing_page(chunk, variant, page_num, category["name"])
                    else:
                        offset = (page_num - 1) * page_size
                        url = category["url"] if page_num == 1 else f"{category['url']}_Desde_{offset + 1}"
                        html = ml_listing_page(chunk, variant, offset, category["name"])

                    name = f"listing_{ctype}_p{page_num}"
                    (root / f"{name}{suffix}.html").write_text(html, encoding="utf-8")
                    index.setdefault(url, f"{name}.html")
                    total_files += 1

            # --- product pages
            for item in items:
                if platform_key == "newegg_us":
                    url = f"https://www.newegg.com/p/{item.sku}"
                    html = newegg_product_page(item, variant)
                else:
                    url = f"https://produto.mercadolivre.com.br/{item.sku}"
                    html = ml_product_page(item, variant)
                name = f"product_{item.sku}"
                (root / f"{name}{suffix}.html").write_text(html, encoding="utf-8")
                index.setdefault(url, f"{name}.html")
                total_files += 1

            # --- homepage banners + featured tiles
            (root / f"homepage{suffix}.html").write_text(
                homepage(platform_key, variant, items), encoding="utf-8"
            )
            index.setdefault(pcfg["homepage"]["url"], "homepage.html")
            total_files += 1

            # --- search results
            kw_cfg = keywords_config()["keyword_sets"][platform_key]
            for group in ("category", "branded"):
                for entry in kw_cfg.get(group, []):
                    keyword = entry["keyword"]
                    slug = keyword.replace(" ", "_")
                    if platform_key == "newegg_us":
                        url = pcfg["search"]["url_template"].format(
                            keyword=keyword.replace(" ", "+"), page=1
                        )
                    else:
                        url = pcfg["search"]["url_template"].format(
                            keyword=keyword.replace(" ", "-")
                        )
                    html = search_page(platform_key, keyword, variant, items)
                    name = f"search_{slug}"
                    (root / f"{name}{suffix}.html").write_text(html, encoding="utf-8")
                    index.setdefault(url, f"{name}.html")
                    total_files += 1

        (root / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
        print(f"  {platform_key:20s} {len(items):3d} SKUs, {len(index):3d} URLs mapped")

    print(f"\nGenerated {total_files} fixture files across {variants} variants.")


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 9
    generate(count)
