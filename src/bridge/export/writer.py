"""PSV and Excel deliverables."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..config import EXPORT_DIR
from ..metrics.competitiveness import competitiveness_score, score_explanation
from ..metrics.core import (
    badge_compliance,
    badge_gaps,
    banner_share,
    brand_compliance_score,
    brand_scoreboard,
    compliance_detail,
    homepage_presence,
    keyword_detail,
    price_index,
    pricing_summary,
    share_of_shelf,
    share_of_voice,
    shelf_position,
)
from ..metrics.frames import alerts_frame, observations_frame, products_frame, runs_frame

log = logging.getLogger(__name__)

PSV_SEP = "|"


def _sheets() -> dict[str, pd.DataFrame]:
    """Build every deliverable table once."""
    return {
        "01_brand_scoreboard": brand_scoreboard(),
        "02_pricing_summary": pricing_summary(),
        "03_price_index": price_index(),
        "04_compliance_score": brand_compliance_score(),
        "05_compliance_detail": compliance_detail(),
        "06_banner_share": banner_share(),
        "07_share_of_shelf": share_of_shelf(),
        "08_shelf_position": shelf_position(),
        "09_badge_compliance": badge_compliance(),
        "10_badge_gaps": badge_gaps(),
        "11_share_of_voice": share_of_voice(),
        "12_homepage_presence": homepage_presence(),
        "13_keyword_detail": keyword_detail(),
        "14_competitiveness": competitiveness_score(),
        "15_alerts": alerts_frame(),
        "16_sku_master": _sku_master(),
        "17_run_log": runs_frame(),
    }


def _sku_master() -> pd.DataFrame:
    """SKU-level export backing the drill-down requirement (module 7)."""
    products = products_frame()
    if products.empty:
        return products

    observations = observations_frame()
    if observations.empty:
        return products

    latest = (
        observations.sort_values("observed_at")
        .groupby("product_id", as_index=False)
        .last()[[
            "product_id", "price_current", "price_was", "currency", "discount_pct",
            "has_promo", "promo_text", "in_stock", "listing_rank", "listing_category",
            "observed_at", "snapshot_path",
        ]]
    )
    merged = products.merge(latest, on="product_id", how="left")
    return merged.sort_values(["platform", "brand", "product_type"])


def _provenance() -> pd.DataFrame:
    """Header block describing the extract."""
    runs = runs_frame()
    window_start = runs["started_at"].min() if not runs.empty else None
    window_end = runs["started_at"].max() if not runs.empty else None
    usable = int((runs["status"].isin(["ok", "partial"])).sum()) if not runs.empty else 0

    fixture_runs = 0
    if not runs.empty and "notes" in runs:
        fixture_runs = usable

    rows = [
        ("generated_at_utc", datetime.now(timezone.utc).isoformat(timespec="seconds")),
        ("runs_total", len(runs) if not runs.empty else 0),
        ("runs_usable", usable),
        ("window_start_utc", str(window_start)),
        ("window_end_utc", str(window_end)),
        ("brand_axis", "chip/SoC supplier (Intel, AMD, Qualcomm, Apple)"),
        ("oem_axis", "device maker — drill-down filter only, never a rollup key"),
        ("currency_policy", "USD and BRL reported separately; never converted or averaged"),
        ("compliance_rollup", "85% notebook / 15% desktop, per brief"),
        ("DATA_SOURCE", "FIXTURE — see docs/DATA_SOURCING.md"),
        ("data_source_note",
         "Newegg and Mercado Libre block datacenter IPs; these figures are computed "
         "by the production pipeline over generated fixture pages, not live retail data."),
    ]
    _ = fixture_runs
    return pd.DataFrame(rows, columns=["field", "value"])


def export_psv(output_dir: Path | None = None) -> list[Path]:
    directory = Path(output_dir or EXPORT_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    target = directory / f"bridge_psv_{stamp}"
    target.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    provenance_path = target / "00_provenance.psv"
    _provenance().to_csv(provenance_path, sep=PSV_SEP, index=False)
    written.append(provenance_path)

    for name, frame in _sheets().items():
        path = target / f"{name}.psv"
        if frame is None or frame.empty:
            pd.DataFrame().to_csv(path, sep=PSV_SEP, index=False)
        else:
            frame.to_csv(path, sep=PSV_SEP, index=False)
        written.append(path)
    return written


def export_excel(output_dir: Path | None = None) -> list[Path]:
    directory = Path(output_dir or EXPORT_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = directory / f"bridge_report_{stamp}.xlsx"

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        _provenance().to_excel(writer, sheet_name="00_README", index=False)

        notes = pd.DataFrame(
            [("competitiveness_score", score_explanation())], columns=["metric", "definition"]
        )
        notes.to_excel(writer, sheet_name="00_definitions", index=False)

        for name, frame in _sheets().items():
            sheet = name[:31]
            if frame is None or frame.empty:
                pd.DataFrame({"note": ["no data for this metric yet"]}).to_excel(
                    writer, sheet_name=sheet, index=False
                )
                continue
            out = frame.copy()
            for col in out.columns:
                if pd.api.types.is_datetime64_any_dtype(out[col]):
                    out[col] = out[col].dt.tz_localize(None) if getattr(
                        out[col].dt, "tz", None
                    ) else out[col]
            out.to_excel(writer, sheet_name=sheet, index=False)

    return [path]


def export_all(fmt: str = "both", output_dir: str | Path | None = None) -> list[Path]:
    directory = Path(output_dir) if output_dir else None
    written: list[Path] = []
    if fmt in ("psv", "both"):
        written += export_psv(directory)
    if fmt in ("excel", "both"):
        written += export_excel(directory)
    return written
