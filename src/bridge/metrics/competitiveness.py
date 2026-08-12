"""Composite competitiveness score (nice-to-have).

Rolls pricing, visibility and compliance into one rankable number per brand,
per the brief's "single combined competitiveness score" suggestion.

The honest caveat, stated here and surfaced in the dashboard: this is a
*constructed* index, not an observation. Its weights are a judgement call, and
different weights produce a different ranking. It earns its place as a
conversation starter — "why is Qualcomm bottom?" — with every pillar
decomposable back to the measured numbers underneath. It should never be quoted
without its components.

One subtlety that is easy to get wrong: price position has no objectively good
direction. A premium brand priced high is executing its strategy, not losing.
The default therefore scores price *stability* (deviation from the brand's own
trailing median) rather than treating cheap as good; `lower_is_better` is
available in config for clients who genuinely want price aggression scored.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import scoring_config, tracked_brands
from .core import (
    banner_share,
    brand_compliance_score,
    price_history,
    pricing_summary,
    share_of_shelf,
    share_of_voice,
)


def _zscore(series: pd.Series, clamp: float) -> pd.Series:
    """Normalise within a comparison group, clamped against outliers.

    Returns 50 for a degenerate group (one brand, or zero variance): with
    nothing to compare against, the neutral midpoint is the only defensible
    answer, and min-max would return 0 or 100 arbitrarily.
    """
    if len(series) < 2:
        return pd.Series([50.0] * len(series), index=series.index)
    std = series.std(ddof=0)
    if not std or np.isnan(std):
        return pd.Series([50.0] * len(series), index=series.index)
    z = ((series - series.mean()) / std).clip(-clamp, clamp)
    # Map [-clamp, +clamp] onto [0, 100].
    return ((z + clamp) / (2 * clamp) * 100).astype(float)


def _price_stability(history: pd.DataFrame) -> pd.DataFrame:
    """Absolute deviation of each brand's latest median price from its trailing median.

    Low deviation = stable positioning = higher score.
    """
    if history.empty:
        return pd.DataFrame(columns=["platform", "brand", "price_deviation_pct"])

    rows = []
    for (platform, brand), chunk in history.groupby(["platform", "brand"]):
        chunk = chunk.sort_values("run_started_at")
        if len(chunk) < 2:
            rows.append({"platform": platform, "brand": brand, "price_deviation_pct": 0.0})
            continue
        trailing = chunk["median_price"].iloc[:-1].median()
        latest = chunk["median_price"].iloc[-1]
        deviation = abs(latest - trailing) / trailing * 100 if trailing else 0.0
        rows.append({"platform": platform, "brand": brand,
                     "price_deviation_pct": round(float(deviation), 3)})
    return pd.DataFrame(rows)


def competitiveness_score(tracked_only: bool = True) -> pd.DataFrame:
    """One composite score per (platform, brand), with its components exposed."""
    cfg = scoring_config()["competitiveness"]
    pillars = cfg["pillars"]
    clamp = float(cfg.get("zscore_clamp", 2.5))
    direction = cfg.get("price_position_direction", "stability")

    # --- gather component metrics, each reduced to latest-per-brand
    shelf = share_of_shelf()
    if not shelf.empty:
        shelf = (shelf.sort_values("date")
                 .groupby(["platform", "brand"], as_index=False).last()
                 [["platform", "brand", "share_pct"]])

    sov = share_of_voice()
    if not sov.empty:
        sov = (sov.sort_values("date")
               .groupby(["platform", "brand"], as_index=False).last()
               [["platform", "brand", "sov_pct"]])

    banner = banner_share()
    if not banner.empty:
        banner = (banner.sort_values("date")
                  .groupby(["platform", "brand"], as_index=False).last()
                  [["platform", "brand", "weighted_share_pct"]]
                  .rename(columns={"weighted_share_pct": "banner_share_pct"}))

    compliance = brand_compliance_score()
    if not compliance.empty:
        compliance = compliance[["platform", "brand", "compliance_score", "coverage_pct"]]

    promo = pricing_summary(by=("platform", "brand"))
    if not promo.empty:
        promo = promo[["platform", "brand", "promo_rate_pct", "avg_discount_pct",
                       "median_price"]]

    stability = _price_stability(price_history())

    base: pd.DataFrame | None = None
    for frame in (shelf, sov, banner, compliance, promo, stability):
        if frame is None or frame.empty:
            continue
        base = frame if base is None else base.merge(
            frame, on=["platform", "brand"], how="outer"
        )
    if base is None or base.empty:
        return pd.DataFrame()

    if tracked_only:
        base = base[base["brand"].isin(tracked_brands())]
    if base.empty:
        return pd.DataFrame()

    base = base.copy()
    # Promo intensity is meaningful as zero (no discounting); a missing
    # compliance score is not, so it stays NaN and is handled per-pillar below.
    for col in ("share_pct", "sov_pct", "banner_share_pct", "promo_rate_pct",
                "avg_discount_pct", "price_deviation_pct"):
        if col in base:
            base[col] = base[col].fillna(0.0)

    # --- normalise each component within its platform
    scored_parts: list[pd.DataFrame] = []
    for platform, chunk in base.groupby("platform"):
        chunk = chunk.copy()

        chunk["n_share_of_shelf"] = _zscore(chunk["share_pct"], clamp)
        chunk["n_share_of_voice"] = _zscore(chunk["sov_pct"], clamp)
        chunk["n_banner_share"] = _zscore(chunk["banner_share_pct"], clamp)
        chunk["n_promo_intensity"] = _zscore(chunk["promo_rate_pct"], clamp)

        if direction == "lower_is_better":
            # Cheaper = more competitive. Invert the median price ranking.
            chunk["n_price_position"] = 100 - _zscore(chunk["median_price"].fillna(0), clamp)
        else:
            # Stability: less deviation scores higher.
            chunk["n_price_position"] = 100 - _zscore(chunk["price_deviation_pct"], clamp)

        if "compliance_score" in chunk and chunk["compliance_score"].notna().any():
            # Compliance is already a 0-100 pass-rate; it is meaningful in
            # absolute terms, so it is used directly rather than normalised
            # against peers. A field where everyone complies should score
            # everyone highly, not force a spread.
            chunk["n_brand_compliance_score"] = chunk["compliance_score"].fillna(
                chunk["compliance_score"].mean()
            )
        else:
            chunk["n_brand_compliance_score"] = 50.0

        scored_parts.append(chunk)

    scored = pd.concat(scored_parts, ignore_index=True)

    # --- weighted rollup
    pillar_scores: dict[str, pd.Series] = {}
    for pillar_name, spec in pillars.items():
        components = spec["components"]
        total = sum(components.values()) or 1.0
        acc = pd.Series(0.0, index=scored.index)
        for component, weight in components.items():
            column = f"n_{component}"
            if column not in scored:
                continue
            acc = acc + scored[column] * (weight / total)
        pillar_scores[pillar_name] = acc
        scored[f"pillar_{pillar_name}"] = acc.round(2)

    weight_total = sum(spec["weight"] for spec in pillars.values()) or 1.0
    composite = pd.Series(0.0, index=scored.index)
    for pillar_name, spec in pillars.items():
        composite = composite + pillar_scores[pillar_name] * (spec["weight"] / weight_total)
    scored["competitiveness_score"] = composite.round(2)

    scored["rank"] = (
        scored.groupby("platform")["competitiveness_score"]
        .rank(ascending=False, method="min").astype(int)
    )

    columns = [
        "platform", "brand", "competitiveness_score", "rank",
        "pillar_pricing", "pillar_visibility", "pillar_compliance",
        "share_pct", "sov_pct", "banner_share_pct", "compliance_score",
        "promo_rate_pct", "avg_discount_pct", "median_price",
        "price_deviation_pct", "coverage_pct",
    ]
    existing = [c for c in columns if c in scored.columns]
    return scored[existing].sort_values(
        ["platform", "competitiveness_score"], ascending=[True, False]
    )


def score_explanation() -> str:
    """Human-readable description of how the score is built, for the dashboard."""
    cfg = scoring_config()["competitiveness"]
    lines = ["Composite score = weighted blend of three pillars:"]
    for name, spec in cfg["pillars"].items():
        components = ", ".join(
            f"{c.replace('_', ' ')} {int(w * 100)}%" for c, w in spec["components"].items()
        )
        lines.append(f"  - {name.title()} ({int(spec['weight'] * 100)}%): {components}")
    lines.append(
        f"Components are z-score normalised within each platform "
        f"(clamped at ±{cfg.get('zscore_clamp', 2.5)}) and mapped to 0-100. "
        f"Price position is scored as '{cfg.get('price_position_direction', 'stability')}'."
    )
    return "\n".join(lines)
