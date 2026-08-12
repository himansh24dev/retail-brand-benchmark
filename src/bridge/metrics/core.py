"""Metric computations for modules 1-6 and 8.

Every function returns a tidy DataFrame keyed on the brand axis, because that
is the axis the brief rolls everything up on. OEM appears only as a column to
filter by, never as a grouping key for a headline number.

Two conventions run through all of it:

* **Shares include an "other" bucket.** Share of Shelf, Share of Voice and
  banner share are all computed against every listing seen, not just the four
  tracked brands. Otherwise the four would always sum to 100% and a brand could
  "gain share" purely because an untracked competitor was delisted.

* **Prices are never converted between currencies.** A USD and a BRL price are
  reported side by side but never averaged. Tax, tariffs and channel margin
  differ enough that a converted average would be a number with no meaning.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import scoring_config, tracked_brands
from .frames import (
    audit_frame,
    badges_frame,
    banners_frame,
    latest_listing_run_ids,
    observations_frame,
    search_frame,
)

# ---------------------------------------------------------------------------
# Module 4: Share of Shelf
# ---------------------------------------------------------------------------


def share_of_shelf(
    df: pd.DataFrame | None = None,
    *,
    by: tuple[str, ...] = ("platform", "date"),
    product_type: str | None = None,
) -> pd.DataFrame:
    """Percentage of listed products belonging to each brand.

    Counts distinct SKUs per run and then averages across the runs in a day, so
    a day with three collection slots is not weighted three times heavier than
    one with a failed slot.
    """
    df = observations_frame() if df is None else df
    if df.empty:
        return pd.DataFrame()
    if product_type:
        df = df[df["product_type"] == product_type]
    if df.empty:
        return pd.DataFrame()

    # Distinct SKUs per run first — a SKU appearing on two listing pages of the
    # same category must not count twice.
    per_run = (
        df.groupby([*by, "run_id", "brand"])["product_id"]
        .nunique()
        .reset_index(name="sku_count")
    )
    per_run["total"] = per_run.groupby([*by, "run_id"])["sku_count"].transform("sum")
    per_run["share_pct"] = per_run["sku_count"] / per_run["total"] * 100

    out = (
        per_run.groupby([*by, "brand"])
        .agg(sku_count=("sku_count", "mean"), share_pct=("share_pct", "mean"))
        .reset_index()
    )
    out["share_pct"] = out["share_pct"].round(2)
    out["sku_count"] = out["sku_count"].round(1)
    return out.sort_values([*by, "share_pct"], ascending=[True] * len(by) + [False])


def shelf_position(df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Where on the page each brand sits.

    Share of Shelf alone can hide a real problem: a brand can hold 30% of
    listings while occupying the bottom of every page. Median rank and
    top-10 share are what make that visible.
    """
    df = observations_frame() if df is None else df
    if df.empty or "listing_rank" not in df:
        return pd.DataFrame()
    df = df[df["listing_rank"].notna()]
    if df.empty:
        return pd.DataFrame()

    latest = latest_listing_run_ids()
    df = df[df["run_id"].isin(latest.values())]
    if df.empty:
        return pd.DataFrame()

    out = (
        df.groupby(["platform", "brand"])
        .agg(
            listings=("product_id", "nunique"),
            median_rank=("listing_rank", "median"),
            best_rank=("listing_rank", "min"),
            top10_count=("listing_rank", lambda s: int((s <= 10).sum())),
            sponsored_count=("is_sponsored", "sum"),
        )
        .reset_index()
    )
    out["top10_share_pct"] = (
        out["top10_count"] / out.groupby("platform")["top10_count"].transform("sum") * 100
    ).round(2)
    return out.sort_values(["platform", "median_rank"])


# ---------------------------------------------------------------------------
# Module 1: Pricing & promotions
# ---------------------------------------------------------------------------


def pricing_summary(
    df: pd.DataFrame | None = None,
    *,
    by: tuple[str, ...] = ("platform", "date", "brand"),
) -> pd.DataFrame:
    """Price level and promotional intensity per brand.

    `promo_rate_pct` is the share of listings on promotion — the headline
    "who is discounting hardest" number. `avg_discount_pct` is conditional on
    being discounted, so a brand that discounts rarely but deeply reads
    differently from one that discounts everything by 5%.
    """
    df = observations_frame() if df is None else df
    if df.empty:
        return pd.DataFrame()
    df = df[df["price_current"].notna()]
    if df.empty:
        return pd.DataFrame()

    out = (
        df.groupby(list(by))
        .agg(
            sku_count=("product_id", "nunique"),
            currency=("currency", "first"),
            avg_price=("price_current", "mean"),
            median_price=("price_current", "median"),
            min_price=("price_current", "min"),
            max_price=("price_current", "max"),
            promo_count=("has_promo", "sum"),
            observations=("observation_id", "count"),
            avg_discount_pct=("discount_pct", "mean"),
        )
        .reset_index()
    )
    out["promo_rate_pct"] = (out["promo_count"] / out["observations"] * 100).round(2)
    for col in ("avg_price", "median_price", "min_price", "max_price"):
        out[col] = out[col].round(2)
    out["avg_discount_pct"] = out["avg_discount_pct"].round(2)
    return out.sort_values(list(by))


def price_index(df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Each brand's median price relative to its comparable set (=100).

    Comparison is within (platform, product_type) only. Indexing a notebook
    against a bare CPU would be meaningless, and indexing across platforms
    would compare currencies.
    """
    df = observations_frame() if df is None else df
    if df.empty:
        return pd.DataFrame()
    df = df[df["price_current"].notna()]
    latest = latest_listing_run_ids()
    df = df[df["run_id"].isin(latest.values())]
    if df.empty:
        return pd.DataFrame()

    grouped = (
        df.groupby(["platform", "product_type", "brand"])
        .agg(median_price=("price_current", "median"),
             sku_count=("product_id", "nunique"),
             currency=("currency", "first"))
        .reset_index()
    )
    segment_median = (
        grouped.groupby(["platform", "product_type"])["median_price"].transform("median")
    )
    grouped["price_index"] = (grouped["median_price"] / segment_median * 100).round(1)
    grouped["median_price"] = grouped["median_price"].round(2)
    return grouped.sort_values(["platform", "product_type", "price_index"])


def price_history(df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per-run average price and promo rate, for trend charts."""
    df = observations_frame() if df is None else df
    if df.empty:
        return pd.DataFrame()
    df = df[df["price_current"].notna()]
    if df.empty:
        return pd.DataFrame()
    out = (
        df.groupby(["platform", "brand", "run_id", "run_started_at", "slot"])
        .agg(
            avg_price=("price_current", "mean"),
            median_price=("price_current", "median"),
            sku_count=("product_id", "nunique"),
            promo_rate_pct=("has_promo", lambda s: round(s.mean() * 100, 2)),
        )
        .reset_index()
        .sort_values("run_started_at")
    )
    out["avg_price"] = out["avg_price"].round(2)
    out["median_price"] = out["median_price"].round(2)
    return out


# ---------------------------------------------------------------------------
# Module 2: Retailer audits -> Brand Compliance Score
# ---------------------------------------------------------------------------


def compliance_detail(df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per-check pass rates, with coverage.

    `coverage_pct` is the share of evaluated (non-null) checks. A 100% pass
    rate on 20% coverage is not a good score — it is an unmeasured one, and the
    dashboard needs both numbers to say so.
    """
    df = audit_frame() if df is None else df
    if df.empty:
        return pd.DataFrame()

    df = df.copy()
    df["evaluated"] = df["passed"].notna()
    df["passed_bool"] = df["passed"].fillna(False).astype(bool)

    out = (
        df.groupby(["platform", "brand", "product_type", "check_code"])
        .agg(
            total=("passed", "size"),
            evaluated=("evaluated", "sum"),
            passed=("passed_bool", "sum"),
        )
        .reset_index()
    )
    out["pass_rate_pct"] = np.where(
        out["evaluated"] > 0, out["passed"] / out["evaluated"] * 100, np.nan
    ).round(2)
    out["coverage_pct"] = (out["evaluated"] / out["total"] * 100).round(2)
    return out


def brand_compliance_score(df: pd.DataFrame | None = None) -> pd.DataFrame:
    """The brief's headline: S1+S2+P1-P5 rolled up, 85% notebook / 15% desktop.

    Product types outside that weighting are still scored and visible in
    drill-down, but excluded from the headline number so it means what the
    brief says it means.
    """
    detail = compliance_detail(df)
    if detail.empty:
        return pd.DataFrame()

    cfg = scoring_config()["audit"]
    check_weights = {code: spec.get("weight", 1.0) for code, spec in cfg["checks"].items()}
    type_weights: dict[str, float] = cfg["product_type_weights"]
    min_coverage = cfg.get("min_coverage_for_confidence", 0.6) * 100

    detail = detail.copy()
    detail["check_weight"] = detail["check_code"].map(check_weights).fillna(1.0)

    # Weighted mean of check pass-rates within each (brand, product_type).
    def _weighted(group: pd.DataFrame) -> pd.Series:
        valid = group[group["pass_rate_pct"].notna()]
        if valid.empty or valid["check_weight"].sum() == 0:
            return pd.Series({"score": np.nan, "coverage_pct": 0.0,
                              "checks_evaluated": 0})
        score = np.average(valid["pass_rate_pct"], weights=valid["check_weight"])
        return pd.Series({
            "score": score,
            "coverage_pct": (valid["evaluated"].sum() / valid["total"].sum() * 100),
            "checks_evaluated": int(valid["evaluated"].sum()),
        })

    by_type = (
        detail.groupby(["platform", "brand", "product_type"])
        .apply(_weighted, include_groups=False)
        .reset_index()
    )

    # Apply the 85/15 rollup across product types.
    headline = by_type[by_type["product_type"].isin(type_weights)].copy()
    if headline.empty:
        return by_type

    headline["type_weight"] = headline["product_type"].map(type_weights)
    headline = headline[headline["score"].notna()]

    def _rollup(group: pd.DataFrame) -> pd.Series:
        weights = group["type_weight"]
        # Renormalise when a brand has no SKUs in one of the two weighted
        # types: an Apple line with notebooks but no gaming desktops should be
        # scored on what it actually sells, not penalised for the gap.
        total_weight = weights.sum()
        if total_weight == 0:
            return pd.Series({"compliance_score": np.nan, "coverage_pct": 0.0})
        return pd.Series({
            "compliance_score": np.average(group["score"], weights=weights),
            "coverage_pct": np.average(group["coverage_pct"], weights=weights),
            "checks_evaluated": int(group["checks_evaluated"].sum()),
            "types_included": ", ".join(sorted(group["product_type"])),
        })

    out = (
        headline.groupby(["platform", "brand"])
        .apply(_rollup, include_groups=False)
        .reset_index()
    )
    out["compliance_score"] = out["compliance_score"].round(2)
    out["coverage_pct"] = out["coverage_pct"].round(2)
    out["low_confidence"] = out["coverage_pct"] < min_coverage
    return out.sort_values(["platform", "compliance_score"], ascending=[True, False])


def compliance_history(df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Compliance score per run, for trend charts."""
    df = audit_frame() if df is None else df
    if df.empty:
        return pd.DataFrame()
    frames = []
    for run_id, chunk in df.groupby("run_id"):
        scored = brand_compliance_score(chunk)
        if scored.empty:
            continue
        scored["run_id"] = run_id
        scored["observed_at"] = chunk["observed_at"].min()
        frames.append(scored)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values("observed_at")


# ---------------------------------------------------------------------------
# Module 6: Badge relevance
# ---------------------------------------------------------------------------


def badge_compliance(df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Eligible-vs-present badge analysis.

    `gap_count` — eligible but absent — is the actionable number. `misapplied`
    (present but not eligible, e.g. an Evo badge on a desktop) is tracked
    separately because it is a different conversation with the retailer.
    """
    df = badges_frame() if df is None else df
    if df.empty:
        return pd.DataFrame()

    df = df.copy()
    df["gap"] = df["is_eligible"] & ~df["is_present"]
    df["misapplied"] = df["is_present"] & ~df["is_eligible"]

    out = (
        df.groupby(["platform", "brand", "badge_name", "page_type"])
        .agg(
            eligible_count=("is_eligible", "sum"),
            present_count=("is_present", "sum"),
            gap_count=("gap", "sum"),
            misapplied_count=("misapplied", "sum"),
            skus=("product_id", "nunique"),
        )
        .reset_index()
    )
    out["compliance_pct"] = np.where(
        out["eligible_count"] > 0,
        (out["eligible_count"] - out["gap_count"]) / out["eligible_count"] * 100,
        np.nan,
    ).round(2)
    return out.sort_values(["platform", "brand", "gap_count"], ascending=[True, True, False])


def badge_gaps(df: pd.DataFrame | None = None, limit: int = 200) -> pd.DataFrame:
    """SKU-level list of missing badges — the drill-down behind the number."""
    df = badges_frame() if df is None else df
    if df.empty:
        return pd.DataFrame()
    gaps = df[df["is_eligible"] & ~df["is_present"]].copy()
    if gaps.empty:
        return pd.DataFrame()
    # Most recent observation per (SKU, badge, page).
    gaps = (
        gaps.sort_values("observed_at")
        .groupby(["product_id", "badge_name", "page_type"], as_index=False)
        .last()
    )
    cols = ["platform", "brand", "badge_name", "page_type", "platform_sku", "title",
            "oem", "product_type", "processor_line", "url", "observed_at"]
    return gaps[[c for c in cols if c in gaps.columns]].head(limit)


# ---------------------------------------------------------------------------
# Module 3: Banner share
# ---------------------------------------------------------------------------


def banner_share(df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Share of homepage banner slots by brand, with hero-slot weighting.

    The hero slot is worth more than the fifth carousel position, so a
    position-weighted share sits alongside the raw count. Raw share alone would
    call a brand with five tail slots a bigger winner than one holding the hero.
    """
    df = banners_frame() if df is None else df
    if df.empty:
        return pd.DataFrame()

    df = df.copy()
    # 1/position weighting: slot 1 = 1.00, slot 2 = 0.50, slot 4 = 0.25.
    df["slot_weight"] = 1.0 / df["slot_position"].clip(lower=1)

    out = (
        df.groupby(["platform", "date", "brand"])
        .agg(
            slot_count=("slot_position", "size"),
            weighted_slots=("slot_weight", "sum"),
            hero_count=("slot_position", lambda s: int((s == 1).sum())),
            with_discount=("has_discount", "sum"),
            with_link=("has_link", "sum"),
            avg_confidence=("brand_confidence", "mean"),
        )
        .reset_index()
    )
    totals = out.groupby(["platform", "date"])[["slot_count", "weighted_slots"]].transform("sum")
    out["share_pct"] = (out["slot_count"] / totals["slot_count"] * 100).round(2)
    out["weighted_share_pct"] = (
        out["weighted_slots"] / totals["weighted_slots"] * 100
    ).round(2)
    out["avg_confidence"] = out["avg_confidence"].round(2)
    return out.sort_values(["platform", "date", "share_pct"], ascending=[True, True, False])


# ---------------------------------------------------------------------------
# Module 8: Share of Voice
# ---------------------------------------------------------------------------


def share_of_voice(df: pd.DataFrame | None = None, *, group: str = "category") -> pd.DataFrame:
    """Rank-weighted search visibility per brand.

    Uses the DCG score recorded at collection time and multiplies by the
    keyword's configured weight, so "gaming laptop" counts for more than
    "gaming tablet". Defaults to category keywords: branded keywords are
    reported separately because a brand ranking first for its own name is
    expected and would drown out the contested terms.
    """
    df = search_frame() if df is None else df
    if df.empty:
        return pd.DataFrame()
    if group:
        df = df[df["keyword_group"] == group]
    if df.empty:
        return pd.DataFrame()

    df = df.copy()
    df["weighted_dcg"] = df["dcg_score"] * df["keyword_weight"]

    out = (
        df.groupby(["platform", "date", "brand"])
        .agg(
            appearances=("rank", "size"),
            weighted_dcg=("weighted_dcg", "sum"),
            best_rank=("rank", "min"),
            median_rank=("rank", "median"),
            top10_count=("rank", lambda s: int((s <= 10).sum())),
            sponsored_count=("is_sponsored", "sum"),
        )
        .reset_index()
    )
    totals = out.groupby(["platform", "date"])["weighted_dcg"].transform("sum")
    out["sov_pct"] = (out["weighted_dcg"] / totals * 100).round(2)
    out["weighted_dcg"] = out["weighted_dcg"].round(3)
    return out.sort_values(["platform", "date", "sov_pct"], ascending=[True, True, False])


def homepage_presence(df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Brand presence in the home page's featured product tiles.

    The other half of the brief's module 8 ("presence and ranking on home page
    and search results pages"). Kept as its own metric rather than folded into
    `share_of_voice`, because a homepage tile and a keyword rank are different
    kinds of visibility and a blended percentage would not survive the question
    "what does this number actually mean?".

    Position is DCG-discounted exactly as search rank is, so a brand holding the
    first tile is not scored level with one in the last row.
    """
    df = search_frame() if df is None else df
    if df.empty or "keyword_group" not in df.columns:
        return pd.DataFrame()
    df = df[df["keyword_group"] == "homepage"]
    if df.empty:
        return pd.DataFrame()

    out = (
        df.groupby(["platform", "date", "brand"])
        .agg(
            tiles=("rank", "size"),
            weighted_dcg=("dcg_score", "sum"),
            best_position=("rank", "min"),
        )
        .reset_index()
    )
    totals = out.groupby(["platform", "date"])["weighted_dcg"].transform("sum")
    out["presence_pct"] = (out["weighted_dcg"] / totals * 100).round(2)
    out["weighted_dcg"] = out["weighted_dcg"].round(3)
    return out.sort_values(["platform", "date", "presence_pct"],
                           ascending=[True, True, False])


def keyword_detail(df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per-keyword brand ranking — which terms a brand wins or loses."""
    df = search_frame() if df is None else df
    if df.empty:
        return pd.DataFrame()
    out = (
        df.groupby(["platform", "keyword", "keyword_group", "brand"])
        .agg(
            appearances=("rank", "size"),
            best_rank=("rank", "min"),
            median_rank=("rank", "median"),
            dcg=("dcg_score", "sum"),
        )
        .reset_index()
    )
    totals = out.groupby(["platform", "keyword"])["dcg"].transform("sum")
    out["sov_pct"] = (out["dcg"] / totals * 100).round(2)
    out["dcg"] = out["dcg"].round(3)
    return out.sort_values(["platform", "keyword", "sov_pct"], ascending=[True, True, False])


# ---------------------------------------------------------------------------
# Cross-module helper
# ---------------------------------------------------------------------------


def brand_scoreboard() -> pd.DataFrame:
    """One row per (platform, brand) joining the headline metric from each module.

    This is the table the brief's "immediately understand how it stacks up"
    requirement points at.
    """
    shelf = share_of_shelf()
    if not shelf.empty:
        shelf = (
            shelf.sort_values("date").groupby(["platform", "brand"], as_index=False).last()
            [["platform", "brand", "share_pct", "sku_count"]]
        )

    sov = share_of_voice()
    if not sov.empty:
        sov = (
            sov.sort_values("date").groupby(["platform", "brand"], as_index=False).last()
            [["platform", "brand", "sov_pct", "median_rank"]]
        )

    banner = banner_share()
    if not banner.empty:
        banner = (
            banner.sort_values("date").groupby(["platform", "brand"], as_index=False).last()
            [["platform", "brand", "weighted_share_pct"]]
            .rename(columns={"weighted_share_pct": "banner_share_pct"})
        )

    compliance = brand_compliance_score()
    if not compliance.empty:
        compliance = compliance[["platform", "brand", "compliance_score",
                                 "coverage_pct", "low_confidence"]]

    pricing = pricing_summary(by=("platform", "brand"))
    if not pricing.empty:
        pricing = pricing[["platform", "brand", "currency", "median_price",
                           "promo_rate_pct", "avg_discount_pct", "sku_count"]]

    out: pd.DataFrame | None = None
    for frame in (shelf, sov, banner, compliance, pricing):
        if frame is None or frame.empty:
            continue
        frame = frame.loc[:, ~frame.columns.duplicated()]
        out = frame if out is None else out.merge(
            frame, on=["platform", "brand"], how="outer", suffixes=("", "_dup")
        )
    if out is None:
        return pd.DataFrame()

    out = out.loc[:, ~out.columns.str.endswith("_dup")]
    out["is_tracked"] = out["brand"].isin(tracked_brands())
    return out.sort_values(["platform", "share_pct"], ascending=[True, False])
