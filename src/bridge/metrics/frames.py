"""DataFrame loaders — the single door between the warehouse and the metrics.

Every metric reads through here so that two rules are enforced in exactly one
place:

1. **Only usable runs count.** A run that was blocked or parsed nothing has a
   truncated product set. Including it would render as a brand's shelf share
   collapsing, when what actually happened is that we failed to fetch. Runs are
   filtered by status, not silently averaged in.

2. **Listing rows drive shelf metrics; product rows drive price detail.** Both
   land in `observation`, and mixing them double-counts a SKU that was seen on
   both. Callers say which they want rather than each re-deriving the filter.
"""

from __future__ import annotations

import functools

import pandas as pd
from sqlalchemy import select

from ..db.models import (
    Alert,
    AuditCheck,
    BadgeObservation,
    BannerObservation,
    Observation,
    Product,
    Run,
    SearchRank,
)
from ..db.session import get_engine, session_scope

# Runs in these states have a complete-enough product set to trust.
USABLE_RUN_STATUSES = ("ok", "partial")


def _read(stmt) -> pd.DataFrame:
    with get_engine().connect() as conn:
        return pd.read_sql(stmt, conn)


def usable_run_ids(run_type: str | None = None) -> list[int]:
    stmt = select(Run.id).where(Run.status.in_(USABLE_RUN_STATUSES), Run.items_parsed > 0)
    if run_type:
        stmt = stmt.where(Run.run_type == run_type)
    with session_scope() as session:
        return [row[0] for row in session.execute(stmt).all()]


def runs_frame() -> pd.DataFrame:
    df = _read(
        select(
            Run.id.label("run_id"), Run.run_type, Run.platform, Run.started_at,
            Run.finished_at, Run.status, Run.slot, Run.items_found, Run.items_parsed,
            Run.fetch_errors, Run.parse_errors, Run.blocked_count, Run.notes,
        )
    )
    if not df.empty:
        df["started_at"] = pd.to_datetime(df["started_at"], utc=True)
        df["date"] = df["started_at"].dt.date
    return df


def products_frame() -> pd.DataFrame:
    return _read(
        select(
            Product.id.label("product_id"), Product.platform, Product.platform_sku,
            Product.url, Product.title, Product.brand, Product.brand_confidence,
            Product.brand_evidence, Product.processor_line, Product.processor_tier,
            Product.oem, Product.oem_sub_brand, Product.product_type,
            Product.is_component, Product.first_seen_at, Product.last_seen_at,
            Product.is_delisted,
        )
    )


def observations_frame(source_page: str | None = "listing") -> pd.DataFrame:
    """Observations joined to their product and run.

    `source_page='listing'` is the default because shelf position, rank and
    the run's full product set only exist on listing rows.
    """
    stmt = (
        select(
            Observation.id.label("observation_id"), Observation.run_id,
            Observation.product_id, Observation.observed_at, Observation.price_current,
            Observation.price_was, Observation.currency, Observation.discount_pct,
            Observation.has_promo, Observation.promo_text, Observation.availability,
            Observation.in_stock, Observation.listing_rank, Observation.listing_page,
            Observation.listing_category, Observation.is_sponsored, Observation.rating,
            Observation.review_count, Observation.source_page,
            Observation.snapshot_path,
            Product.platform, Product.platform_sku, Product.title, Product.brand,
            Product.brand_confidence, Product.processor_line, Product.processor_tier,
            Product.oem, Product.oem_sub_brand, Product.product_type,
            Product.is_component, Product.url,
            Run.slot, Run.status.label("run_status"), Run.started_at.label("run_started_at"),
        )
        .join(Product, Product.id == Observation.product_id)
        .join(Run, Run.id == Observation.run_id)
        .where(Run.status.in_(USABLE_RUN_STATUSES))
    )
    if source_page:
        stmt = stmt.where(Observation.source_page == source_page)

    df = _read(stmt)
    if df.empty:
        return df
    df["observed_at"] = pd.to_datetime(df["observed_at"], utc=True)
    df["run_started_at"] = pd.to_datetime(df["run_started_at"], utc=True)
    df["date"] = df["observed_at"].dt.date
    return df


def audit_frame() -> pd.DataFrame:
    stmt = (
        select(
            AuditCheck.run_id, AuditCheck.product_id, AuditCheck.observed_at,
            AuditCheck.check_code, AuditCheck.page_type, AuditCheck.passed,
            AuditCheck.evidence, AuditCheck.snapshot_path,
            # Brand and product_type come from the audit row, NOT from Product.
            # Joining to the live dimension would retroactively relabel every
            # historical check when a SKU's attribution changes, silently
            # rewriting compliance scores that were already reported.
            AuditCheck.brand, AuditCheck.product_type,
            Product.platform, Product.oem,
            Product.title, Product.platform_sku, Product.processor_line,
            Run.slot,
        )
        .join(Product, Product.id == AuditCheck.product_id)
        .join(Run, Run.id == AuditCheck.run_id)
        .where(Run.status.in_(USABLE_RUN_STATUSES))
    )
    df = _read(stmt)
    if df.empty:
        return df
    df["observed_at"] = pd.to_datetime(df["observed_at"], utc=True)
    df["date"] = df["observed_at"].dt.date
    return df


def badges_frame() -> pd.DataFrame:
    stmt = (
        select(
            BadgeObservation.run_id, BadgeObservation.product_id,
            BadgeObservation.observed_at, BadgeObservation.brand,
            BadgeObservation.badge_name, BadgeObservation.page_type,
            BadgeObservation.is_eligible, BadgeObservation.is_present,
            BadgeObservation.evidence,
            Product.platform, Product.oem, Product.product_type, Product.title,
            Product.platform_sku, Product.processor_line, Product.url,
        )
        .join(Product, Product.id == BadgeObservation.product_id)
        .join(Run, Run.id == BadgeObservation.run_id)
        .where(Run.status.in_(USABLE_RUN_STATUSES))
    )
    df = _read(stmt)
    if df.empty:
        return df
    df["observed_at"] = pd.to_datetime(df["observed_at"], utc=True)
    df["date"] = df["observed_at"].dt.date
    return df


def banners_frame() -> pd.DataFrame:
    stmt = (
        select(
            BannerObservation.run_id, BannerObservation.platform,
            BannerObservation.observed_at, BannerObservation.slot_position,
            BannerObservation.slot_type, BannerObservation.image_url,
            BannerObservation.link_url, BannerObservation.alt_text,
            BannerObservation.brand, BannerObservation.brand_confidence,
            BannerObservation.oem, BannerObservation.has_link,
            BannerObservation.has_discount, BannerObservation.discount_text,
            BannerObservation.badges_detected,
        )
        .join(Run, Run.id == BannerObservation.run_id)
        .where(Run.status.in_(USABLE_RUN_STATUSES))
    )
    df = _read(stmt)
    if df.empty:
        return df
    df["observed_at"] = pd.to_datetime(df["observed_at"], utc=True)
    df["date"] = df["observed_at"].dt.date
    # Unattributed banners are a real category, not a null to drop: they are
    # inventory no tracked brand won.
    df["brand"] = df["brand"].fillna("other")
    return df


def search_frame() -> pd.DataFrame:
    stmt = (
        select(
            SearchRank.run_id, SearchRank.platform, SearchRank.observed_at,
            SearchRank.keyword, SearchRank.keyword_group, SearchRank.keyword_weight,
            SearchRank.page, SearchRank.rank, SearchRank.product_id, SearchRank.title,
            SearchRank.brand, SearchRank.oem, SearchRank.is_sponsored,
            SearchRank.dcg_score,
        )
        .join(Run, Run.id == SearchRank.run_id)
        .where(Run.status.in_(USABLE_RUN_STATUSES))
    )
    df = _read(stmt)
    if df.empty:
        return df
    df["observed_at"] = pd.to_datetime(df["observed_at"], utc=True)
    df["date"] = df["observed_at"].dt.date
    return df


def alerts_frame() -> pd.DataFrame:
    df = _read(
        select(
            Alert.id.label("alert_id"), Alert.run_id, Alert.created_at, Alert.alert_type,
            Alert.severity, Alert.platform, Alert.brand, Alert.oem, Alert.product_id,
            Alert.product_type, Alert.prev_value, Alert.new_value, Alert.delta,
            Alert.message, Alert.acknowledged,
        )
    )
    if not df.empty:
        df["created_at"] = pd.to_datetime(df["created_at"], utc=True)
        df["date"] = df["created_at"].dt.date
    return df


def latest_listing_run_ids() -> dict[str, int]:
    """Most recent usable listing run per platform.

    Snapshot metrics ("what does the shelf look like now?") must read one run
    per platform, not a blend of the last few, or a SKU seen twice is counted
    twice.
    """
    with session_scope() as session:
        rows = session.execute(
            select(Run.platform, Run.id, Run.started_at)
            .where(Run.run_type == "listing", Run.status.in_(USABLE_RUN_STATUSES))
            .order_by(Run.platform, Run.started_at.desc())
        ).all()
    latest: dict[str, int] = {}
    for platform, run_id, _ in rows:
        latest.setdefault(platform, run_id)
    return latest


@functools.lru_cache(maxsize=1)
def _warn_once() -> None:  # pragma: no cover - convenience for empty databases
    print("No usable runs found. Run `python -m bridge build-history` first.")
