"""Change detection (nice-to-have: "simple alerts/flags")."""

from __future__ import annotations

import logging

import pandas as pd
from sqlalchemy import select

from ..config import scoring_config
from ..db.models import Alert, Run
from ..db.session import session_scope
from .core import share_of_shelf
from .frames import badges_frame, observations_frame

log = logging.getLogger(__name__)


def _two_latest_runs(platform: str) -> tuple[int | None, int | None]:
    with session_scope() as session:
        rows = session.execute(
            select(Run.id)
            .where(
                Run.platform == platform,
                Run.run_type == "listing",
                Run.status.in_(("ok", "partial")),
                Run.items_parsed > 0,
            )
            .order_by(Run.started_at.desc())
            .limit(2)
        ).all()
    ids = [row[0] for row in rows]
    current = ids[0] if ids else None
    previous = ids[1] if len(ids) > 1 else None
    return current, previous


def generate_alerts() -> int:
    """Compare the latest run against the previous one and persist new alerts."""
    cfg = scoring_config()["alerts"]
    observations = observations_frame()
    if observations.empty:
        return 0

    created = 0
    for platform in sorted(observations["platform"].unique()):
        current_run, previous_run = _two_latest_runs(platform)
        if current_run is None or previous_run is None:
            continue

        pending: list[dict] = []
        pending += _price_and_promo_alerts(observations, platform, current_run, previous_run, cfg)
        pending += _stock_alerts(observations, platform, current_run, previous_run, cfg)
        pending += _lifecycle_alerts(observations, platform, current_run, previous_run, cfg)
        pending += _badge_alerts(platform, current_run, previous_run, cfg)
        pending += _shelf_alerts(platform, cfg)

        created += _persist(pending, current_run, platform)

    return created


def _pair_runs(
    df: pd.DataFrame, platform: str, current_run: int, previous_run: int
) -> pd.DataFrame:
    """Join a SKU's current and previous observation side by side."""
    subset = df[(df["platform"] == platform) & df["run_id"].isin([current_run, previous_run])]
    if subset.empty:
        return pd.DataFrame()

    current = subset[subset["run_id"] == current_run]
    previous = subset[subset["run_id"] == previous_run]
    current = current.sort_values("observed_at").groupby("product_id", as_index=False).last()
    previous = previous.sort_values("observed_at").groupby("product_id", as_index=False).last()

    return current.merge(previous, on="product_id", suffixes=("", "_prev"), how="inner")


def _price_and_promo_alerts(df, platform, current_run, previous_run, cfg) -> list[dict]:
    paired = _pair_runs(df, platform, current_run, previous_run)
    if paired.empty:
        return []

    valid = paired[paired["price_current"].notna() & paired["price_current_prev"].notna()]
    valid = valid[valid["price_current_prev"] > 0]
    if valid.empty:
        return []

    change_pct = (
        (valid["price_current"] - valid["price_current_prev"])
        / valid["price_current_prev"] * 100
    )

    out: list[dict] = []
    drop_threshold = -abs(cfg["price_drop"]["threshold_pct"])
    rise_threshold = abs(cfg["price_rise"]["threshold_pct"])

    for row, pct in zip(valid.to_dict("records"), change_pct):
        if pct <= drop_threshold:
            out.append(_alert_dict(
                row, "price_drop", cfg["price_drop"]["severity"], platform,
                prev=f"{row['price_current_prev']:.2f}",
                new=f"{row['price_current']:.2f}", delta=round(pct, 2),
                message=(f"{row['brand'].title()} {row['platform_sku']} price fell "
                         f"{abs(pct):.1f}% ({row['currency']} {row['price_current_prev']:,.2f} "
                         f"-> {row['price_current']:,.2f})"),
            ))
        elif pct >= rise_threshold:
            out.append(_alert_dict(
                row, "price_rise", cfg["price_rise"]["severity"], platform,
                prev=f"{row['price_current_prev']:.2f}",
                new=f"{row['price_current']:.2f}", delta=round(pct, 2),
                message=(f"{row['brand'].title()} {row['platform_sku']} price rose "
                         f"{pct:.1f}% ({row['currency']} {row['price_current_prev']:,.2f} "
                         f"-> {row['price_current']:,.2f})"),
            ))

        if bool(row["has_promo"]) and not bool(row["has_promo_prev"]):
            out.append(_alert_dict(
                row, "promo_started", cfg["promo_started"]["severity"], platform,
                prev="none", new=str(row.get("promo_text") or "promo"),
                message=(f"{row['brand'].title()} {row['platform_sku']} started a promotion: "
                         f"{row.get('promo_text') or 'discount applied'}"),
            ))
        elif not bool(row["has_promo"]) and bool(row["has_promo_prev"]):
            out.append(_alert_dict(
                row, "promo_ended", cfg["promo_ended"]["severity"], platform,
                prev=str(row.get("promo_text_prev") or "promo"), new="none",
                message=f"{row['brand'].title()} {row['platform_sku']} promotion ended",
            ))
    return out


def _stock_alerts(df, platform, current_run, previous_run, cfg) -> list[dict]:
    paired = _pair_runs(df, platform, current_run, previous_run)
    if paired.empty:
        return []
    went_oos = paired[(paired["in_stock"] == False) & (paired["in_stock_prev"] == True)]  # noqa: E712
    return [
        _alert_dict(row, "out_of_stock", cfg["out_of_stock"]["severity"], platform,
                    prev="in stock", new="out of stock",
                    message=(f"{row['brand'].title()} {row['platform_sku']} went out of stock"))
        for row in went_oos.to_dict("records")
    ]


def _lifecycle_alerts(df, platform, current_run, previous_run, cfg) -> list[dict]:
    subset = df[(df["platform"] == platform) & df["run_id"].isin([current_run, previous_run])]
    if subset.empty:
        return []
    current_ids = set(subset[subset["run_id"] == current_run]["product_id"])
    previous_ids = set(subset[subset["run_id"] == previous_run]["product_id"])

    new_ids = current_ids - previous_ids
    rows = subset[subset["product_id"].isin(new_ids) & (subset["run_id"] == current_run)]
    rows = rows.groupby("product_id", as_index=False).last()

    out = [
        _alert_dict(row, "new_sku", cfg["new_sku"]["severity"], platform,
                    prev="absent", new="listed",
                    message=(f"New {row['brand'].title()} SKU listed: "
                             f"{str(row['title'])[:90]}"))
        for row in rows.to_dict("records")
    ]

    with session_scope() as session:
        from ..db.models import Product

        delisted = session.execute(
            select(Product).where(
                Product.platform == platform,
                Product.is_delisted.is_(True),
            )
        ).scalars().all()
        for product in delisted:
            out.append({
                "alert_type": "delisted_sku",
                "severity": cfg["delisted_sku"]["severity"],
                "platform": platform,
                "brand": product.brand,
                "oem": product.oem,
                "product_id": product.id,
                "product_type": product.product_type,
                "prev_value": "listed",
                "new_value": "delisted",
                "delta": None,
                "message": (f"{product.brand.title()} SKU delisted after "
                            f"{product.consecutive_absences} absences: "
                            f"{product.title[:90]}"),
                "dedupe_key": f"delisted_sku|{platform}|{product.id}",
            })
    return out


def _badge_alerts(platform, current_run, previous_run, cfg) -> list[dict]:
    badges = badges_frame()
    if badges.empty:
        return []
    subset = badges[
        (badges["platform"] == platform) & badges["run_id"].isin([current_run, previous_run])
    ]
    if subset.empty:
        return []

    key = ["product_id", "badge_name", "page_type"]
    current = subset[subset["run_id"] == current_run].groupby(key, as_index=False).last()
    previous = subset[subset["run_id"] == previous_run].groupby(key, as_index=False).last()
    paired = current.merge(previous, on=key, suffixes=("", "_prev"), how="inner")
    if paired.empty:
        return []

    out: list[dict] = []
    disappeared = paired[
        paired["is_eligible"] & ~paired["is_present"] & paired["is_present_prev"]
    ]
    for row in disappeared.to_dict("records"):
        out.append({
            "alert_type": "badge_disappeared",
            "severity": cfg["badge_disappeared"]["severity"],
            "platform": platform,
            "brand": row["brand"],
            "oem": row.get("oem"),
            "product_id": int(row["product_id"]),
            "product_type": row.get("product_type"),
            "prev_value": "present",
            "new_value": "absent",
            "delta": None,
            "message": (f"{row['badge_name']} badge disappeared from "
                        f"{row['page_type']} page: {str(row['title'])[:80]}"),
            "dedupe_key": (f"badge_disappeared|{platform}|{row['product_id']}|"
                           f"{row['badge_name']}|{row['page_type']}"),
        })

    appeared = paired[paired["is_present"] & ~paired["is_present_prev"]]
    for row in appeared.to_dict("records"):
        out.append({
            "alert_type": "badge_appeared",
            "severity": cfg["badge_appeared"]["severity"],
            "platform": platform,
            "brand": row["brand"],
            "oem": row.get("oem"),
            "product_id": int(row["product_id"]),
            "product_type": row.get("product_type"),
            "prev_value": "absent",
            "new_value": "present",
            "delta": None,
            "message": (f"{row['badge_name']} badge now shown on "
                        f"{row['page_type']} page: {str(row['title'])[:80]}"),
            "dedupe_key": (f"badge_appeared|{platform}|{row['product_id']}|"
                           f"{row['badge_name']}|{row['page_type']}"),
        })
    return out


def _shelf_alerts(platform, cfg) -> list[dict]:
    """Fire when a brand's share of shelf moves by more than N percentage points."""
    shelf = share_of_shelf(by=("platform", "date"))
    if shelf.empty:
        return []
    shelf = shelf[shelf["platform"] == platform].sort_values("date")
    if shelf["date"].nunique() < 2:
        return []

    dates = sorted(shelf["date"].unique())
    latest, prior = dates[-1], dates[-2]
    current = shelf[shelf["date"] == latest].set_index("brand")["share_pct"]
    before = shelf[shelf["date"] == prior].set_index("brand")["share_pct"]

    threshold = cfg["share_of_shelf_swing"]["threshold_points"]
    out: list[dict] = []
    for brand in current.index.union(before.index):
        now = float(current.get(brand, 0.0))
        was = float(before.get(brand, 0.0))
        delta = now - was
        if abs(delta) < threshold:
            continue
        direction = "gained" if delta > 0 else "lost"
        out.append({
            "alert_type": "share_of_shelf_swing",
            "severity": cfg["share_of_shelf_swing"]["severity"],
            "platform": platform,
            "brand": brand,
            "oem": None,
            "product_id": None,
            "product_type": None,
            "prev_value": f"{was:.2f}%",
            "new_value": f"{now:.2f}%",
            "delta": round(delta, 2),
            "message": (f"{str(brand).title()} {direction} {abs(delta):.1f}pt of shelf "
                        f"share ({was:.1f}% -> {now:.1f}%)"),
            "dedupe_key": f"share_of_shelf_swing|{platform}|{brand}|{latest}",
        })
    return out


def _alert_dict(row, alert_type, severity, platform, *, prev, new, message,
                delta=None) -> dict:
    return {
        "alert_type": alert_type,
        "severity": severity,
        "platform": platform,
        "brand": row.get("brand"),
        "oem": row.get("oem"),
        "product_id": int(row["product_id"]),
        "product_type": row.get("product_type"),
        "prev_value": prev,
        "new_value": new,
        "delta": delta,
        "message": message,
        "dedupe_key": f"{alert_type}|{platform}|{row['product_id']}|{new}",
    }


def _persist(pending: list[dict], run_id: int, platform: str) -> int:
    if not pending:
        return 0
    with session_scope() as session:
        existing = {
            row[0] for row in session.execute(
                select(Alert.dedupe_key).where(Alert.platform == platform)
            ).all()
        }
        created = 0
        for payload in pending:
            if payload["dedupe_key"] in existing:
                continue
            session.add(Alert(run_id=run_id, **payload))
            existing.add(payload["dedupe_key"])
            created += 1
    if created:
        log.info("[%s] %d new alerts", platform, created)
    return created
