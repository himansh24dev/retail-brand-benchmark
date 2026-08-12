"""Database schema."""

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


class Run(Base):
    """One collection execution."""

    __tablename__ = "run"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_type: Mapped[str] = mapped_column(String(32))
    platform: Mapped[str] = mapped_column(String(32), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="running")
    slot: Mapped[str | None] = mapped_column(String(16), nullable=True)

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
        """Whether metrics should include this run."""
        return self.status in ("ok", "partial") and self.items_parsed > 0


class FetchLog(Base):
    """Per-request diagnostics."""

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


class Product(Base):
    """A SKU on a platform, with its attributed brand/OEM/type."""

    __tablename__ = "product"

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), index=True)
    platform_sku: Mapped[str] = mapped_column(String(128))
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)

    brand: Mapped[str] = mapped_column(String(32), default="other", index=True)
    brand_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    brand_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    processor_line: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    processor_tier: Mapped[str | None] = mapped_column(String(32), nullable=True)

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


class Observation(Base):
    """Module 1 (pricing & promotions) + module 4 (share of shelf) source rows."""

    __tablename__ = "observation"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("run.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    price_current: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_was: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(8))
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

    source_page: Mapped[str] = mapped_column(String(16), default="listing")
    snapshot_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped["Run"] = relationship(back_populates="observations")
    product: Mapped["Product"] = relationship(back_populates="observations")

    __table_args__ = (
        Index("ix_obs_product_observed", "product_id", "observed_at"),
        Index("ix_obs_run_product", "run_id", "product_id"),
    )


class ProductSpec(Base):
    """Module 5: full specs per product."""

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
    """Module 2: one row per rubric check per product per run."""

    __tablename__ = "audit_check"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("run.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    check_code: Mapped[str] = mapped_column(String(8), index=True)
    page_type: Mapped[str] = mapped_column(String(16))
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    brand: Mapped[str] = mapped_column(String(32), default="other", index=True)
    product_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    snapshot_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_audit_product_run_code", "product_id", "run_id", "check_code"),
        Index("ix_audit_observed_code", "observed_at", "check_code"),
    )


class BadgeObservation(Base):
    """Module 6: badge detection with eligibility."""

    __tablename__ = "badge_observation"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("run.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    brand: Mapped[str] = mapped_column(String(32), index=True)
    badge_name: Mapped[str] = mapped_column(String(64), index=True)
    page_type: Mapped[str] = mapped_column(String(16))
    is_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    is_present: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_badge_product_run", "product_id", "run_id"),
        Index("ix_badge_brand_observed", "brand", "observed_at"),
    )


class BannerObservation(Base):
    """Module 3: homepage banner slots."""

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
    """Module 8: share of voice."""

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
    """Nice-to-have: change detection."""

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
