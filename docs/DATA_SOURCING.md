# Data Sourcing — read this first

**The figures in this project are computed from generated fixture pages, not from
live Newegg or Mercado Libre data.**

This is stated up front, in the dashboard on every page, and in the header of
every export, because a number whose provenance is unclear is worse than no
number at all.

---

## What was attempted

Live collection was tried against both platforms before falling back. Every
avenue was blocked:

| Attempt | Method | Result |
|---|---|---|
| Newegg listing page | Playwright (real Chromium, stealth flags, realistic UA/locale) | HTTP 200 → redirected to `/areyouahuman`, title *"Are you a human?"* |
| Newegg internal JSON | `httpx` against `/api/ProductList` | Same interstitial |
| Mercado Libre listing | `httpx` HTTP/2 | HTTP 302 → `/gz/account-verification` |
| Mercado Libre listing | Playwright | Same redirect |
| Mercado Libre public API | `api.mercadolibre.com/sites/MLB/search` | `403 forbidden` |
| Mercado Libre API (any endpoint) | `api.mercadolibre.com/sites/MLB` | `403 PA_UNAUTHORIZED_RESULT_FROM_POLICIES` |

Both sites run commercial bot protection that rejects datacenter IP ranges
regardless of how the request is presented. Mercado Libre's public search API,
which was historically open, now requires OAuth credentials.

This is not a defect that more effort fixes. It is the normal operating
condition for retail scraping, and it is why competitive-intelligence vendors
budget for residential proxy infrastructure.

### A note on the block signal

Both platforms return **HTTP 200 with a full-sized body** on the challenge page.
Status-code checks and content-length checks both pass. Only the redirect target
reveals the block, which is why `block_url_signals` exists in
`config/platforms.yaml` alongside the body-text signals — a collector that
checked only the status code would have recorded "0 products found" as a real
shelf collapse.

---

## What the fixtures are, and are not

**They are** HTML pages generated to mirror each platform's real DOM structure,
built from a hand-written catalogue of 72 realistic SKUs
(`tests/fixtures/catalog.py`) covering all four tracked brands, all seven OEMs,
every product type in scope, plus NVIDIA-only, MediaTek and unattributable SKUs
so the Share-of-Shelf denominator is honest.

The production selector chains in `config/platforms.yaml` resolve against them
unchanged. **The parsers under test are the parsers that will run live.**

Nine variants are generated, replayed as nine successive collection runs
(≈3 days at the brief's 3×-daily cadence). Drift between variants — price
movement, promotions starting and ending, badges appearing and disappearing,
shelf reordering — is deterministic and seeded, so any run reproduces exactly.

**They are not** a substitute for real market data. Specifically:

- Absolute price levels are plausible but invented. No conclusion about what
  Intel actually charges on Newegg can be drawn from them.
- Compliance rates are driven by `BADGE_RATE` / `BRAND_MEDIA_RATE` constants
  chosen to exercise the scoring logic and produce a readable spread. **The
  finding "Qualcomm has the weakest badge compliance" is a property of the
  fixture constants, not of the real market.**
- Search rankings come from a crude token-overlap heuristic, not a real search
  engine.

Drift is applied to the *rendered HTML only*. Nothing is injected at the metrics
layer — every number in the dashboard is computed by the real pipeline from
these pages, so the pipeline's correctness is genuinely demonstrated even though
its inputs are synthetic.

---

## Going live

Switching to real collection is a **transport change**. No metric, schema,
scoring or dashboard code changes.

### Option 1 — Scraping API / residential proxy (covers both platforms)

```bash
export BRIDGE_PROXY="http://user:pass@proxy-host:port"
# or per-platform:
export BRIDGE_PROXY_NEWEGG_US="http://..."
export BRIDGE_PROXY_MERCADOLIBRE_BR="http://..."

python -m bridge collect --mode live
```

`Fetcher` reads these automatically and applies them to both the httpx client
and the Playwright browser. Nothing is committed; credentials stay in the
environment.

Providers with free tiers sufficient for a week of 3×-daily runs: ScraperAPI,
ScrapingBee, Zyte. For production volume: Bright Data, Oxylabs.

### Option 2 — Mercado Libre official API (covers Brazil properly, free)

Register an application at <https://developers.mercadolivre.com.br> for OAuth
credentials. This is the correct long-term answer for the Brazil half: it is
documented, permitted, rate-limited rather than blocked, and returns structured
data rather than HTML that must be parsed.

It would require a new collector implementing the same `BaseCollector` contract
(~150 lines) — the normalisation, metrics and dashboard layers consume it
unchanged. Newegg has no equivalent public API, so it still needs Option 1.

### Verifying the switch

```bash
python -m bridge collect --module listing --mode live --max-pages 1
python -m bridge status
```

Check the `run_log` for `blocked_count`. A healthy live run reports
`status=ok` with `blocked_count=0`. Any block is recorded per-URL in the
`fetch_log` table with the snapshot path, so a failure is diagnosable rather
than silent.

---

## Rate limiting and conduct

The collectors are deliberately polite, and this should be preserved on any
live deployment:

- Per-platform request ceilings (8/min Newegg, 15/min Mercado Libre) with
  randomised jitter — periodic requests are a stronger bot signal than volume.
- Escalating backoff on any detected block (15 min Newegg, 10 min Mercado
  Libre, multiplied by consecutive block count, capped at 1 hour).
- Images, fonts and media are blocked at the browser layer — roughly an order of
  magnitude less bandwidth drawn from the retailer, since only markup is parsed.
- Product-page audits are restricted to tracked-brand SKUs rather than the
  whole catalogue.

Before running this against live sites at scale, confirm the arrangement with
Bridge AI — commercial scraping of retail platforms is normal practice in this
industry, but the terms are a commercial question, not a technical one.
