"""Database schema.

Design note: this is a snapshot warehouse, not a current-state store. Nothing
is ever updated in place except slowly-changing dimension fields on `Product`.
Every collection run appends a fresh row to the fact tables with its own
`observed_at`.

That single decision is what makes the brief's requirements fall out cheaply:

  * price/promo history (module 1)   -> filter Observation by time
  * share of shelf trend (module 4)  -> group Observation by run
  * alerts (nice-to-have)            -> compare consecutive Observations
  * "why did this number change?"    -> every row keeps its raw HTML path

The cost is table growth. At ~3 runs/day x 2 platforms x ~2k SKUs that is
~12k observation rows/day, which SQLite handles without complaint for the
horizon this project covers. `snapshot_path` keeps the bulky HTML on disk
rather than in the database.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Run bookkeeping
# ---------------------------------------------------------------------------


class Run(Base):
    """One collection execution.

    Every fact row points at a Run. This is what lets the dashboard say "as of
    the 14:00 run" rather than "as of some time today", and what makes a
    partial or failed run excludable from metrics instead of quietly skewing
    them.
    """

    __tablename__ = "run"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_type: Mapped[str] = mapped_column(String(32))  # listing|product|banner|search
    platform: Mapped[str] = mapped_column(String(32), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|ok|partial|failed
    slot: Mapped[str | None] = mapped_column(String(16), nullable=True)  # morning|midday|evening

    pages_fetched: Mapped[int] = mapped_column(Integer, default=0)
    items_found: Mapped[int] = mapped_column(Integer, default=0)
    items_parsed: Mapped[int] = mapped_column(Integer, default=0)
    fetch_errors: Mapped[int] = mapped_column(Integer, default=0)
    parse_errors: Mapped[int] = mapped_column(Integer, default=0)
    blocked_count: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    observations: Mapped[list["Observation"]] = relationship(back_populates="run")

    __table_args__ = (Index("ix_run_platform_started", "platform", "started_at"),)

    @property
    def is_usable(self) -> bool:
        """Whether metrics should include this run.

        A run that was blocked partway through has a truncated product set,
        which would read as a share-of-shelf collapse rather than as missing
        data. Excluding it is the honest choice.
        """
        return self.status in ("ok", "partial") and self.items_parsed > 0


class FetchLog(Base):
    """Per-request diagnostics.

    Kept separate from Run because the failure modes that matter here (block
    rates, latency creep, selector drift) are per-URL, and diagnosing them
    after the fact is otherwise guesswork.
    """

    __tablename__ = "fetch_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("run.id"), nullable=True, index=True)
    url: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(16), default="browser")
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snapshot_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


# ---------------------------------------------------------------------------
# Dimension: the SKU
# ---------------------------------------------------------------------------


class Product(Base):
    """A SKU on a platform, with its attributed brand/OEM/type.

    Attribution lives here rather than on Observation because it is a property
    of the product, not of the moment it was seen. When a title changes enough
    to flip attribution, `attribution_changed_at` records it — that is a real
    retail event (a relist), not a bug to smooth over.
    """

    __tablename__ = "product"

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), index=True)
    platform_sku: Mapped[str] = mapped_column(String(128))
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)

    # --- Brand axis (the chip/SoC supplier) — every metric rolls up here.
    brand: Mapped[str] = mapped_column(String(32), default="other", index=True)
    brand_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    brand_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    processor_line: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    processor_tier: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # --- OEM axis (the device maker) — drill-down filter only.
    # NULL is meaningful and correct for standalone CPU/GPU components.
    oem: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    oem_sub_brand: Mapped[str | None] = mapped_column(String(64), nullable=True)

    product_type: Mapped[str] = mapped_column(String(32), index=True)
    is_component: Mapped[bool] = mapped_column(Boolean, default=False)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    attribution_changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    consecutive_absences: Mapped[int] = mapped_column(Integer, default=0)
    is_delisted: Mapped[bool] = mapped_column(Boolean, default=False)

    observations: Mapped[list["Observation"]] = relationship(back_populates="product")

    __table_args__ = (
        UniqueConstraint("platform", "platform_sku", name="uq_product_platform_sku"),
        Index("ix_product_brand_type", "brand", "product_type"),
        Index("ix_product_platform_brand", "platform", "brand"),
    )


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------


class Observation(Base):
    """Module 1 (pricing & promotions) + module 4 (share of shelf) source rows.

    One row per product per run. `listing_rank` doubles as the shelf-position
    signal: share of shelf counts these rows, and rank distribution shows
    whether a brand holds the top of the page or the tail of it.
    """

    __tablename__ = "observation"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("run.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    price_current: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_was: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(8))
    # Stored rather than derived so a later change to discount logic cannot
    # silently rewrite history.
    discount_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    has_promo: Mapped[bool] = mapped_column(Boolean, default=False)
    promo_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    availability: Mapped[str | None] = mapped_column(String(32), nullable=True)
    in_stock: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    listing_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    listing_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    listing_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_sponsored: Mapped[bool] = mapped_column(Boolean, default=False)

    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    source_page: Mapped[str] = mapped_column(String(16), default="listing")  # listing|product
    snapshot_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped["Run"] = relationship(back_populates="observations")
    product: Mapped["Product"] = relationship(back_populates="observations")

    __table_args__ = (
        Index("ix_obs_product_observed", "product_id", "observed_at"),
        Index("ix_obs_run_product", "run_id", "product_id"),
    )


class ProductSpec(Base):
    """Module 5: full specs per product.

    Key/value rather than wide columns — the spec vocabulary differs per
    platform, per category and per locale (pt-BR vs en-US), and a wide table
    would be permanently behind. `key_normalized` maps both vocabularies onto a
    shared set so cross-platform comparison is possible.

    Written only when the spec set actually changes, since specs are near-static
    and a row per run would be almost entirely duplicates.
    """

    __tablename__ = "product_spec"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("run.id"), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    key_raw: Mapped[str] = mapped_column(String(128))
    key_normalized: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    value_raw: Mapped[str] = mapped_column(Text)
    value_normalized: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_spec_product_key", "product_id", "key_normalized"),)


class AuditCheck(Base):
    """Module 2: one row per rubric check per product per run.

    `passed` is deliberately nullable. NULL means "could not evaluate" (the
    product page did not load, the spec table was absent) and is excluded from
    the score denominator — scoring it as a failure would blame a brand for our
    own collection gap. `coverage` in the metrics layer reports how often this
    happens, so a low-confidence score is visibly low-confidence.
    """

    __tablename__ = "audit_check"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("run.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    check_code: Mapped[str] = mapped_column(String(8), index=True)  # S1,S2,P1..P5
    page_type: Mapped[str] = mapped_column(String(16))  # listing|product
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # Brand and product type are denormalised onto the fact row deliberately.
    # Reading them from Product at query time would rewrite history: when a
    # retailer edits a title and attribution flips, every past audit row for
    # that SKU would silently move to the new brand, changing compliance
    # scores for weeks already reported. A fact must carry the dimension
    # values it was observed with.
    brand: Mapped[str] = mapped_column(String(32), default="other", index=True)
    product_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    snapshot_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_audit_product_run_code", "product_id", "run_id", "check_code"),
        Index("ix_audit_observed_code", "observed_at", "check_code"),
    )


class BadgeObservation(Base):
    """Module 6: badge detection with eligibility.

    Both halves are recorded: `is_eligible` (should this badge be here, given
    the processor line and product type) and `is_present` (is it). A compliance
    gap is eligible AND NOT present. Recording presence alone would make it
    impossible to tell a genuine gap from a badge that never applied.
    """

    __tablename__ = "badge_observation"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("run.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    brand: Mapped[str] = mapped_column(String(32), index=True)
    badge_name: Mapped[str] = mapped_column(String(64), index=True)
    page_type: Mapped[str] = mapped_column(String(16))  # listing|product
    is_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    is_present: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_badge_product_run", "product_id", "run_id"),
        Index("ix_badge_brand_observed", "brand", "observed_at"),
    )


class BannerObservation(Base):
    """Module 3: homepage banner slots.

    Banners carry no SKU, so brand attribution runs over alt text, link URL and
    surrounding copy — weaker evidence than a product title, which is why
    `brand_confidence` is stored and surfaced rather than hidden.
    """

    __tablename__ = "banner_observation"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("run.id"), index=True)
    platform: Mapped[str] = mapped_column(String(32), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    slot_position: Mapped[int] = mapped_column(Integer)
    slot_type: Mapped[str] = mapped_column(String(32), default="hero")
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    link_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    alt_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    brand: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    brand_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    oem: Mapped[str | None] = mapped_column(String(32), nullable=True)
    has_link: Mapped[bool] = mapped_column(Boolean, default=False)
    has_discount: Mapped[bool] = mapped_column(Boolean, default=False)
    discount_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    badges_detected: Mapped[str | None] = mapped_column(Text, nullable=True)
    snapshot_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_banner_platform_observed", "platform", "observed_at"),)


class SearchRank(Base):
    """Module 8: share of voice.

    One row per result position per keyword per run. Storing every position
    (not just the tracked brands') keeps the denominator honest and lets the
    dashboard show who is actually occupying the slots a brand is missing.
    """

    __tablename__ = "search_rank"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("run.id"), index=True)
    platform: Mapped[str] = mapped_column(String(32), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    keyword: Mapped[str] = mapped_column(String(128), index=True)
    keyword_group: Mapped[str] = mapped_column(String(16), default="category")
    keyword_weight: Mapped[float] = mapped_column(Float, default=1.0)
    page: Mapped[int] = mapped_column(Integer, default=1)
    rank: Mapped[int] = mapped_column(Integer)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("product.id"), nullable=True)
    title: Mapped[str] = mapped_column(Text)
    brand: Mapped[str] = mapped_column(String(32), index=True)
    oem: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_sponsored: Mapped[bool] = mapped_column(Boolean, default=False)
    dcg_score: Mapped[float] = mapped_column(Float, default=0.0)
    snapshot_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_rank_keyword_observed", "keyword", "observed_at"),
        Index("ix_rank_brand_observed", "brand", "observed_at"),
    )


class Alert(Base):
    """Nice-to-have: change detection.

    Alerts are materialised rather than computed on read so that an alert
    reflects the comparison as it was made, and so acknowledging one is
    meaningful. `dedupe_key` prevents the same unchanged condition from
    re-firing on every run.
    """

    __tablename__ = "alert"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("run.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    alert_type: Mapped[str] = mapped_column(String(48), index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    platform: Mapped[str] = mapped_column(String(32), index=True)
    brand: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    oem: Mapped[str | None] = mapped_column(String(32), nullable=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("product.id"), nullable=True)
    product_type: Mapped[str | None] = mapped_column(String(32), nullable=True)

    prev_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    message: Mapped[str] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(String(255), index=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (Index("ix_alert_created_severity", "created_at", "severity"),)
