# Retail Price, Promotion & Brand Positioning — Multi-Brand Benchmark

A daily competitive benchmark of how **Intel, AMD, Qualcomm and Apple** are
priced, promoted and displayed across **Newegg (US)** and **Mercado Libre
(Brazil)**, gaming segment.

This is a side-by-side comparison, not a single-brand dashboard. Every metric
rolls up on the **brand** (chip/SoC supplier) axis; **OEM** (Dell, HP, Lenovo,
Acer, ASUS, MSI, Apple) is an independent drill-down filter and never a rollup
key.

> ### ⚠️ Data source
> **Figures are computed from generated fixture pages, not live retail data.**
> Newegg and Mercado Libre both block datacenter IPs — verified, with the
> evidence and the path to live collection in
> **[docs/DATA_SOURCING.md](docs/DATA_SOURCING.md)**. The pipeline is
> production-shaped: the parsers, metrics and scoring that produce these numbers
> are the ones that will run against live pages. Only the transport is
> substituted.

---

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium        # only needed for live collection

export PYTHONPATH=src

.venv/bin/python -m bridge init-db
.venv/bin/python -m bridge build-history --runs 9   # ~9 runs ≈ 3 days of cadence
.venv/bin/python -m bridge export --format both

.venv/bin/streamlit run src/dashboard/app.py        # → http://localhost:8501
```

`build-history` replays nine fixture variants as nine successive collection
runs, so trends, alerts and slot-over-slot comparisons have real inputs.

A prebuilt warehouse (`data/bridge.db`) is committed, so `streamlit run` works
straight after cloning and the hosted link opens instantly. It is fully derived:
delete it and run `build-history` to rebuild it. The dashboard also builds its
own warehouse on first boot if none is present, which is what makes a hosted
deployment work with no shell access.

The fixture pages themselves are generated artefacts and are not in git, so the
first `build-history` builds them automatically (a few seconds, one time). To
build them explicitly — or to rebuild after editing the catalogue:

```bash
.venv/bin/python tests/fixtures/generate.py 9   # 9 variants → 1026 pages
```

---

## What it measures

Each module maps to a section of the brief.

| # | Module | Cadence | Where it lives |
|---|--------|---------|----------------|
| 1 | **Pricing & promotions** — price, was-price, discount %, promo text, stock | 3×/day | `collect/retail.py` → `metrics/core.py:pricing_summary` |
| 2 | **Retailer audits** — S1, S2, P1–P5 → Brand Compliance Score (85% notebook / 15% desktop) | 3×/day | `normalize/audit_checks.py` → `metrics/core.py:brand_compliance_score` |
| 3 | **Banner tracking** — homepage slots, brand, link, discount | daily | `collect/banners.py` → `metrics/core.py:banner_share` |
| 4 | **Share of Shelf** — % of listings per brand, trended | every run | `metrics/core.py:share_of_shelf` |
| 5 | **Product data attributes** — full specs, normalised across en-US/pt-BR | every run | `normalize/specs.py` |
| 6 | **Badge types & relevance** — eligibility-gated badge detection | every run | `normalize/badges.py` → `metrics/core.py:badge_compliance` |
| 7 | **SKU explorer** — search, filter, drill-down to the product driving a number | — | `dashboard/app.py:page_sku_explorer` |
| 8 | **Share of Voice** — rank-weighted search presence per keyword set, plus home-page presence | 3×/day | `collect/search.py` → `metrics/core.py:share_of_voice`, `homepage_presence` |

Plus the nice-to-haves: a **composite competitiveness score**, **change
alerts**, and **historical trend views** throughout.

---

## Architecture

```
config/*.yaml          Brand taxonomy, selectors, keywords, scoring weights.
                       No brand name, CSS selector or weight is hardcoded in Python.
   │
   ▼
collect/               fetcher.py    — httpx + Playwright, rate limiting, block
                                       detection, gzipped HTML evidence store
                       retail.py     — listings + product pages (modules 1,2,4,5,6)
                       banners.py    — homepage carousel (module 3)
                       search.py     — keyword rankings + home-page
                                       presence (module 8)
   │
   ▼
normalize/             attribution.py — brand / OEM / product type
                       price.py       — USD vs BRL parsing, promo detection
                       badges.py      — detection + eligibility
                       specs.py       — en-US / pt-BR spec vocabulary
                       audit_checks.py— the S1/S2/P1–P5 rubric
   │
   ▼
db/                    Snapshot warehouse. Nothing is updated in place; every
                       run appends with its own observed_at.
   │
   ▼
metrics/               core.py, competitiveness.py, alerts.py
   │
   ├──► export/        PSV + Excel (19 sheets, provenance header)
   └──► dashboard/     Streamlit
```

### The one design decision that matters most

The warehouse is **snapshot-per-run**, not current-state. Every collection run
appends fresh rows rather than updating. This is why the brief's harder
requirements are cheap rather than bolted on:

- price/promo history → filter observations by time
- Share of Shelf trend → group observations by run
- alerts → compare consecutive runs
- *"why did this number change?"* → every row keeps its raw HTML snapshot path

---

## Correctness decisions worth knowing

These are the non-obvious calls. Each exists because the naive version produced
a wrong number.

**Discrete GPUs never attribute a system.** A "Lenovo Legion, Ryzen 7, RTX 4070"
is an AMD system. Counting the RTX token would hand roughly a third of gaming
laptops to NVIDIA and deflate every tracked brand's shelf share. The rule
inverts for standalone graphics cards, where the GPU *is* the product. It is
enforced in both the processor-line pass and the brand-name fallback — the
fallback was the subtler of the two bugs.

**Badge presence is read from badge markup only.** Product titles and spec
tables contain the exact strings badge patterns match ("AMD Ryzen 7…"), so
scanning full page text marked the badge present on nearly every SKU. S2 became
a duplicate of S1 and reported ~100% compliance. Badge checks now read only
badge elements.

**Unevaluable checks are excluded, not failed.** If a product page did not load,
P1–P5 are unknowable. Recording them as failures would make compliance scores
track our own uptime. They are `NULL`, excluded from the denominator, and
surfaced as `coverage %`.

**Facts carry their own dimensions.** Audit rows store the brand they were
observed with rather than joining to the live product row. Otherwise a retailer
editing a title would retroactively relabel every historical audit row and
silently rewrite compliance scores already reported.

**Shares include an "other" bucket.** Share of Shelf, Share of Voice and banner
share are computed against every listing seen. Without the residual bucket, the
four tracked brands would always sum to 100% and a brand would appear to gain
share whenever an untracked competitor was delisted.

**Prices are never converted between currencies.** USD and BRL sit side by side,
never averaged. Brazilian retail embeds tariffs, ICMS and different channel
margins; a converted average has no real-world referent.

**Blocks are detected by redirect URL, not status code.** Both platforms serve
their challenge page with HTTP 200 and a full-sized body. A collector checking
only status and length would record "0 products found" as a genuine shelf
collapse.

---

## CLI

```bash
python -m bridge init-db [--drop]
python -m bridge collect --module {all,listing,banner,search} \
                         --mode {auto,fixture,live} [--platform newegg_us]
python -m bridge build-history --runs 9
python -m bridge metrics                     # recompute alerts
python -m bridge export --format {psv,excel,both}
python -m bridge schedule [--once]           # 3×/day cadence
python -m bridge status                      # warehouse summary
```

`--mode live` is the switch to real collection; see
[docs/DATA_SOURCING.md](docs/DATA_SOURCING.md) for the proxy configuration it
needs.

### Scheduler

Three fixed UTC slots — 06:00, 13:00, 20:00 — rather than "every 8 hours", so
runs land at comparable times each day. Retail pricing is diurnal; a drifting
schedule would show phantom movement. Banner tracking runs on the morning slot
only (daily, per the brief). The monthly benchmark export runs on the 1st.

---

## Tests

```bash
.venv/bin/python tests/test_attribution.py     # 34 cases
```

Weighted toward the adversarial cases, since attribution errors propagate into
every metric simultaneously: CPU/GPU brand conflicts, Apple's short chip tokens
colliding with "M.2" storage, components cross-listed into system categories,
and the discrete-GPU fallback regression.

---

## Documentation

| Document | Contents |
|---|---|
| **[docs/DATA_SOURCING.md](docs/DATA_SOURCING.md)** | What was attempted against live sites, what blocked it, and exactly how to go live |
| **[docs/QUESTIONS.md](docs/QUESTIONS.md)** | Assumptions made (with reasoning) and open questions for Bridge AI |

---

## Layout

```
config/          brands.yaml · platforms.yaml · oems.yaml · keywords.yaml · scoring.yaml
src/bridge/      collect/ · normalize/ · metrics/ · db/ · export/ · schedule/ · cli.py
src/dashboard/   app.py · theme.py
tests/           test_attribution.py · fixtures/ (catalog.py, generate.py, 1026 pages)
data/            bridge.db · raw/ (gzipped HTML evidence)
exports/         PSV directories + Excel workbooks
```
