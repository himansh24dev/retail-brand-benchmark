# Questions & Assumptions

The brief asks for questions and clarifications to be documented. This is that
document.

It is split into two parts: **decisions I had to make to finish the build**
(each with the reasoning, each cheap to reverse), and **open questions** where
your answer would change the output. Nothing here blocked delivery — everything
is implemented under a stated assumption.

---

## Part 1 — Decisions made, and why

### 1.1 The seven audit checks are equally weighted

The brief specifies the 85% notebook / 15% desktop rollup, but not the relative
weight of S1, S2 and P1–P5 within a product. Equal weighting is the neutral
default.

Per-check weights are already exposed in `config/scoring.yaml` → `audit.checks`,
so if badge presence (S2/P2) matters more to you than OEM rich media (P5), it is
a config edit, not a code change.

> **Question:** should any check carry more weight than the others?

### 1.2 Unevaluable checks are excluded from the denominator, not scored as failures

If a product page fails to load, P1–P5 are unknowable. Scoring them as failures
would blame a brand for our collection gap and make compliance scores track our
uptime rather than the retailer's behaviour.

Instead they are recorded as `NULL`, excluded from the score, and reported as
`coverage %`. A score below 60% coverage is flagged as low-confidence in the
dashboard.

### 1.3 Share of Shelf includes an "Other / unattributed" bucket

Shares are computed against *every* listing seen, not just the four tracked
brands. Without this, the four would always sum to 100% and a brand would appear
to gain share whenever an untracked competitor was delisted.

This means the four tracked brands sum to less than 100%. That is intentional.

### 1.4 Prices are never converted between currencies

USD and BRL are reported side by side but never averaged or converted. Brazilian
retail pricing embeds import tariffs, ICMS and very different channel margins;
a converted average would be a number with no real-world referent. Every
price chart is per-platform for this reason.

> **Question:** do you want an FX-normalised view as well? It is easy to add, but
> I would want it labelled as indicative rather than comparable.

### 1.5 Discrete GPUs do not attribute a system

A "Lenovo Legion, Ryzen 7, RTX 4070" is recorded as **AMD** — the chip/SoC
supplier — with NVIDIA appearing nowhere in its brand attribution. The GPU
attributes the product only when the GPU *is* the product (a standalone graphics
card).

Without this rule, roughly a third of gaming laptops would be attributed to
NVIDIA and every tracked brand's shelf share would be understated.

> **Question:** do you want discrete GPU vendor tracked as a *separate* attribute
> (e.g. "AMD CPU + NVIDIA GPU" as a combination)? The data supports it; it is
> currently only surfaced in the spec table.

### 1.6 "Price position" is scored as stability, not cheapness

For the composite competitiveness score, treating a lower price as automatically
"more competitive" would penalise Apple for executing a premium strategy. The
default scores *deviation from the brand's own trailing median* — i.e. is this
brand's positioning stable or moving.

`config/scoring.yaml` → `competitiveness.price_position_direction` switches it to
`lower_is_better` if you want price aggression scored directly.

> **Question:** which reading do you want?

### 1.7 Badge presence is read from badge markup only, never page text

An early version detected badges anywhere on the page. This scored ~100%
compliance for every brand, because the *title* ("AMD Ryzen 7…") and the spec
table both contain the exact strings the badge patterns match. S2 became a copy
of S1 and the check measured nothing.

Badge detection now reads only badge elements (image `alt` attributes, dedicated
badge containers). This is stricter and may under-count a badge rendered as
styled text rather than an image.

> **Question:** if you have the actual badge markup specs the retailers are
> contractually required to use, I can target them precisely and remove this
> trade-off.

### 1.8 Eligibility gates every badge finding

A missing "Intel Evo" badge on a desktop is not a compliance gap — Evo is a
laptop-only certification. Each badge declares which processor lines and product
types it applies to; a gap is *eligible AND absent*.

The eligibility rules in `config/brands.yaml` are my best reconstruction from
public information.

> **Question:** can you share the authoritative badge eligibility matrix? This is
> the single input most likely to be wrong, and it directly drives modules 2
> and 6.

### 1.9 Alerts compare consecutive runs and are deduplicated

A price that drops 20% and stays there is one event, not one per run forever.
Alerts carry a dedupe key; an unchanged condition produces no new alert.

Delisting requires **three consecutive absences on healthy runs** — a single
failed fetch must never look like a product going away.

### 1.10 Search rank is discounted logarithmically

Share of Voice weights position 1 far above position 20 (standard DCG discount)
rather than counting appearances. Results past rank 50 score zero. Category
(brand-neutral) keywords and branded keywords are reported separately, because a
brand ranking first for its own name is expected and would drown out the
contested terms.

> **Question:** the keyword sets in `config/keywords.yaml` are my own
> construction. Do you have the actual keyword list Bridge AI tracks, or search
> volume data to weight them by? Right now weights are judgement calls.

### 1.11 Home-page presence is reported beside Share of Voice, not blended into it

Module 8 asks for presence and ranking on **the home page and search results
pages**. Both are collected. They are reported as two numbers rather than one.

Blending them would require asserting an exchange rate between "holds tile 3 on
the homepage" and "ranks #4 for *gaming laptop*" — and any single figure built on
that guess cannot be explained in a sentence, which is the bar every number here
has to clear. Homepage tiles are position-discounted on the same DCG curve, so
the two are directly comparable when read side by side.

Note this is the *organic* featured grid, deliberately separate from the
carousel banners in module 3: those are merchandised placements, and a brand can
hold banner space while being absent from the featured tiles. That contrast is
itself a finding.

`config/keywords.yaml` → `homepage_presence.blend_weight` (default 0.25) is the
weight a combined figure would use.

> **Question:** do you want a single blended visibility number? If so, is 0.25
> the right weight for the homepage relative to the ten-keyword set?

### 1.12 Monthly cadence covers Share of Shelf and the benchmark export

Per the brief, price/promo/audits/banners run 3×/day and the brand benchmark is
monthly. Share of Shelf is *computed* on every run (it is free — it falls out of
the listing data already collected) but the **benchmark deliverable** is the
monthly export.

### 1.13 "Screenshots" is implemented as raw HTML snapshots

The brief lists screenshots under the monthly deliverable. Every fetched page is
stored gzipped on disk and referenced from the database, so any number traces
back to the exact bytes it came from. This is more useful than a PNG for
auditing and far cheaper to store.

> **Question:** do you need actual rendered images (for a slide deck or a
> compliance record), or is the HTML evidence trail sufficient? Adding PNG
> capture is a small change to the fetch layer.

---

## Part 2 — Open questions

These would change the output and I would rather ask than guess.

### On scope

1. **"Gaming segment" boundary.** I filter by category (Newegg's Gaming Laptops,
   Mercado Libre's `notebook-gamer`, etc.). But a Dell XPS with an RTX card is
   arguably a gaming machine listed in a non-gaming category, and a "gaming"
   category contains plenty of non-gaming SKUs. Should the boundary be the
   retailer's category, a spec-based rule (has discrete GPU?), or a keyword rule?

2. **Workstations and tablets.** Both are in scope per the brief, but neither
   appears in the 85/15 compliance rollup. They are collected and scored, and
   visible in drill-down, but excluded from the headline compliance number.
   Correct?

3. **Marketplace sellers on Mercado Libre.** ML is a marketplace — the same SKU
   appears from many sellers at different prices. I currently treat each listing
   as its own SKU. Should I deduplicate to a canonical product and take the buy
   box price instead? This materially changes Share of Shelf.

4. **Refurbished / used listings.** Currently included. They drag median prices
   down noticeably on Mercado Libre. Exclude?

5. **Apple in a gaming benchmark.** Apple is a tracked brand, but Apple does not
   market gaming machines and neither retailer merchandises MacBooks that way.
   Apple currently sits alongside the other three in the gaming categories, which
   keeps the comparison meaningful. My concern is what happens on live data:
   filtering strictly by each retailer's gaming categories would likely drop
   Apple to near-zero shelf share on both platforms. Do you want Apple measured
   inside the gaming boundary and reported as near-absent, or pulled from the
   general notebook/desktop categories so there is something to compare against?

### On measurement

6. **Which currency for the Brazil price benchmark** — BRL only, or also an
   FX-normalised USD view? (See 1.4.)

7. **Compliance target.** Is there a contractual threshold (e.g. "95% of eligible
   SKUs must show the badge")? Right now the score is reported without a target
   line, so "81.5" has no pass/fail context.

8. **Banner attribution confidence.** Banners carry no SKU, so brand attribution
   runs over alt text and link slug. Roughly 15–30% of slots are unattributable
   generic merchandising. Should those be excluded from banner share, or kept in
   the denominator as "inventory no brand won"? Currently kept.

9. **Sponsored listings.** Both platforms mix paid placements into listing and
   search results. I flag them (`is_sponsored`) but currently count them in Share
   of Shelf and Share of Voice, on the basis that a shopper sees them either way.
   The alternative reading is that bought visibility is not the same as won
   visibility. Do you want shares organic-only, with sponsored reported beside
   them?

10. **Which price counts.** Newegg shows a list price, a promo-code price and
    sometimes a member price; Mercado Libre shows an installment price next to
    the cash price. I record the headline price a shopper sees first, before
    entering any code. That understates real discounting where the saving is
    behind a coupon. Is headline price the right basis?

11. **Out-of-stock SKUs in Share of Shelf.** Shelf share counts listing rows, and
    a listing tile does not reliably show stock — availability only becomes
    visible on the product page (where 33 of 572 observations are currently out
    of stock). So an unbuyable SKU still holds shelf share today. That is
    defensible as "visibility" and misleading as "availability". Which should it
    mean? If the latter, I would gate shelf share on the product-page stock flag
    and accept the coverage gap that creates.

### On delivery

12. **Who consumes the PSV/Excel exports** — a human in Excel, or a downstream
    system? If it is a system, I would want to agree a stable schema and stop
    changing column names between versions.

13. **Alert delivery.** Alerts are currently stored and shown in the dashboard.
    Do you want them pushed (email/Slack/webhook)? And what severity threshold
    warrants a push?

14. **Retention.** Every run stores raw HTML. At the brief's cadence across both
    platforms that is roughly 1–2 GB/month uncompressed. What retention window
    do you want, and is object storage available or should it stay on local
    disk?

15. **Collection times.** The three daily slots are fixed at 06:00, 13:00 and
    20:00 UTC so runs stay comparable day to day. That lands at 03:00 / 10:00 /
    17:00 in Brazil and 22:00 / 05:00 / 12:00 US Pacific — comparable, but not
    aligned to either market's shopping hours. Would you rather I set per-market
    slots and give up direct cross-market comparability?

### On the data-access constraint

16. **This is the one that needs an answer soonest.** Both platforms block
    datacenter IPs (see `DATA_SOURCING.md`). Live collection needs either a
    residential proxy / scraping API, or Mercado Libre OAuth credentials for the
    Brazil half. Which does Bridge AI already have, or which would you like me to
    set up? Everything else is built and waiting on transport.
