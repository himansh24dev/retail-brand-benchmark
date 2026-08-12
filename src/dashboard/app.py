"""Streamlit dashboard — the online deliverable."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bridge.config import brand_display_names, tracked_brands  # noqa: E402
from bridge.metrics import core  # noqa: E402
from bridge.metrics.competitiveness import competitiveness_score, score_explanation  # noqa: E402
from bridge.metrics.frames import (  # noqa: E402
    alerts_frame,
    banners_frame,
    observations_frame,
    products_frame,
    runs_frame,
    search_frame,
)
from dashboard.theme import (  # noqa: E402
    SEQUENTIAL_BLUE,
    SEVERITY_COLORS,
    STATUS,
    SURFACE,
    TEXT_PRIMARY,
    brand_bar,
    brand_color,
    brand_label,
    brand_lines,
    style,
)

st.set_page_config(
    page_title="Retail Brand Benchmark",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

TTL = 300

BOOTSTRAP_RUNS = 9


@st.cache_resource(show_spinner=False)
def bootstrap_warehouse() -> int:
    """Build the warehouse on first boot if it is empty."""
    from bridge.cli import build_history
    from bridge.db.session import init_db

    init_db()
    try:
        if not runs_frame().empty:
            return 0
    except Exception:              # noqa: BLE001 - unreadable DB => rebuild it
        pass

    with st.spinner(
        f"First run on this server — building the demo warehouse "
        f"({BOOTSTRAP_RUNS} collection runs, about a minute). "
        "This happens once."
    ):
        return build_history(runs=BOOTSTRAP_RUNS, quiet=True)


@st.cache_data(ttl=TTL)
def load_runs() -> pd.DataFrame:
    return runs_frame()


@st.cache_data(ttl=TTL)
def load_observations() -> pd.DataFrame:
    return observations_frame()


@st.cache_data(ttl=TTL)
def load_products() -> pd.DataFrame:
    return products_frame()


@st.cache_data(ttl=TTL)
def load_scoreboard() -> pd.DataFrame:
    return core.brand_scoreboard()


@st.cache_data(ttl=TTL)
def load_shelf() -> pd.DataFrame:
    return core.share_of_shelf()


@st.cache_data(ttl=TTL)
def load_compliance() -> pd.DataFrame:
    return core.brand_compliance_score()


@st.cache_data(ttl=TTL)
def load_compliance_detail() -> pd.DataFrame:
    return core.compliance_detail()


@st.cache_data(ttl=TTL)
def load_sov() -> pd.DataFrame:
    return core.share_of_voice()


@st.cache_data(ttl=TTL)
def load_banner() -> pd.DataFrame:
    return core.banner_share()


@st.cache_data(ttl=TTL)
def load_badges() -> pd.DataFrame:
    return core.badge_compliance()


@st.cache_data(ttl=TTL)
def load_alerts() -> pd.DataFrame:
    return alerts_frame()


@st.cache_data(ttl=TTL)
def load_competitiveness() -> pd.DataFrame:
    return competitiveness_score()


@st.cache_data(ttl=TTL)
def load_price_history() -> pd.DataFrame:
    return core.price_history()


def data_source_banner() -> None:
    """Non-dismissible provenance notice."""
    st.info(
        "**Demonstration data.** Both retailers block automated collection from "
        "datacenter networks, so these figures run against representative sample "
        "pages rather than live listings. The collection, parsing, attribution and "
        "scoring pipeline is production code — only the data source is substituted.",
        icon="ℹ️",
    )


def table_view(df: pd.DataFrame, label: str = "Show underlying data") -> None:
    """Table companion for every chart — the accessibility relief path."""
    if df is None or df.empty:
        return
    with st.expander(label):
        st.dataframe(df, use_container_width=True, hide_index=True)


def platform_filter(df: pd.DataFrame, key: str) -> tuple[pd.DataFrame, str]:
    if df.empty or "platform" not in df:
        return df, "All"
    options = ["All"] + sorted(df["platform"].unique())
    choice = st.selectbox("Platform", options, key=key, format_func=_platform_label)
    if choice == "All":
        return df, choice
    return df[df["platform"] == choice], choice


def _platform_label(key: str) -> str:
    return {
        "All": "All platforms",
        "newegg_us": "Newegg (US)",
        "mercadolibre_br": "Mercado Libre (Brazil)",
    }.get(key, key)


def empty_state() -> None:
    st.info(
        "No data yet. Build the warehouse first:\n\n"
        "```bash\npython -m bridge init-db\npython -m bridge build-history --runs 9\n```"
    )


def page_overview() -> None:
    st.title("Brand Benchmark")
    st.caption(
        "Side-by-side comparison of Intel, AMD, Qualcomm and Apple across Newegg (US) "
        "and Mercado Libre (Brazil), gaming segment. Every metric rolls up on the "
        "**brand** (chip/SoC supplier) axis; OEM is a drill-down filter only."
    )
    data_source_banner()

    runs = load_runs()
    if runs.empty:
        empty_state()
        return

    scoreboard = load_scoreboard()
    usable = runs[runs["status"].isin(["ok", "partial"])]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Collection runs", f"{len(runs):,}", f"{len(usable)} usable")
    c2.metric("SKUs tracked", f"{len(load_products()):,}")
    c3.metric("Observations", f"{len(load_observations()):,}")
    alerts = load_alerts()
    high = int((alerts["severity"] == "high").sum()) if not alerts.empty else 0
    c4.metric("Open alerts", f"{len(alerts):,}", f"{high} high severity",
              delta_color="inverse")

    st.divider()

    st.subheader("Share of Shelf")
    st.caption(
        "Percentage of listed gaming products belonging to each brand. The "
        "*Other / unattributed* bucket is included so shares sum to 100% — without "
        "it, a brand would appear to gain share whenever an untracked competitor "
        "was delisted."
    )
    shelf = load_shelf()
    if not shelf.empty:
        latest_date = shelf["date"].max()
        current = shelf[shelf["date"] == latest_date]
        cols = st.columns(len(current["platform"].unique()))
        for col, (platform, chunk) in zip(cols, current.groupby("platform")):
            with col:
                st.markdown(f"**{_platform_label(platform)}**")
                chunk = chunk.sort_values("share_pct", ascending=True)
                st.plotly_chart(
                    brand_bar(chunk, x="share_pct", y="brand", suffix="%"),
                    use_container_width=True,
                    key=f"shelf_{platform}",
                )
        table_view(current, "Share of Shelf — underlying data")

    st.divider()

    st.subheader("Cross-module scoreboard")
    st.caption(
        "One row per brand per platform, joining the headline number from each "
        "module. This is the 'how does it stack up' view."
    )
    if not scoreboard.empty:
        display = scoreboard.copy()
        display["brand"] = display["brand"].map(brand_label)
        display["platform"] = display["platform"].map(_platform_label)
        rename = {
            "platform": "Platform", "brand": "Brand", "share_pct": "Shelf %",
            "sku_count": "SKUs", "sov_pct": "SoV %", "median_rank": "Median rank",
            "banner_share_pct": "Banner %", "compliance_score": "Compliance",
            "coverage_pct": "Coverage %", "median_price": "Median price",
            "promo_rate_pct": "Promo %", "avg_discount_pct": "Avg discount %",
            "currency": "Currency",
        }
        cols = [c for c in rename if c in display.columns]
        st.dataframe(
            display[cols].rename(columns=rename),
            use_container_width=True, hide_index=True,
        )


def page_pricing() -> None:
    st.title("Pricing & Promotions")
    st.caption(
        "Module 1. Collected 3x daily. **Prices are never converted between "
        "currencies** — USD and BRL are reported separately, because tax, tariffs "
        "and channel margin differ enough that a converted average would be "
        "meaningless."
    )
    data_source_banner()

    pricing = core.pricing_summary(by=("platform", "brand"))
    if pricing.empty:
        empty_state()
        return

    filtered, choice = platform_filter(pricing, "pricing_platform")

    st.subheader("Promotional intensity")
    st.caption(
        "Share of listings currently on promotion — the 'who is discounting "
        "hardest' number. Average discount is conditional on being discounted, so "
        "a brand that discounts rarely but deeply reads differently from one "
        "discounting everything by 5%."
    )
    for platform, chunk in filtered.groupby("platform"):
        st.markdown(f"**{_platform_label(platform)}**")
        chunk = chunk.sort_values("promo_rate_pct")
        st.plotly_chart(
            brand_bar(chunk, x="promo_rate_pct", y="brand", suffix="%"),
            use_container_width=True, key=f"promo_{platform}",
        )
    table_view(filtered, "Pricing summary — underlying data")

    st.divider()
    st.subheader("Median price by brand")
    st.caption("Separate chart per platform — one axis per currency, never combined.")
    for platform, chunk in filtered.groupby("platform"):
        currency = chunk["currency"].iloc[0] if "currency" in chunk else ""
        st.markdown(f"**{_platform_label(platform)}** · {currency}")
        chunk = chunk.sort_values("median_price")
        st.plotly_chart(
            brand_bar(chunk, x="median_price", y="brand",
                      text_fmt="{:,.0f}", suffix=f" {currency}"),
            use_container_width=True, key=f"price_{platform}",
        )

    st.divider()
    st.subheader("Price trend")
    st.caption("Median price per collection run. Each platform is charted separately.")
    history = load_price_history()
    if not history.empty:
        for platform, chunk in history.groupby("platform"):
            if choice != "All" and platform != choice:
                continue
            st.markdown(f"**{_platform_label(platform)}**")
            st.plotly_chart(
                brand_lines(chunk, x="run_started_at", y="median_price"),
                use_container_width=True, key=f"pricehist_{platform}",
            )
        table_view(history, "Price history — underlying data")

    st.divider()
    st.subheader("Price index")
    st.caption(
        "Each brand's median price relative to its comparable set (=100), within "
        "platform and product type. A premium brand indexing high is executing its "
        "strategy — this is positioning, not a scorecard."
    )
    index = core.price_index()
    if not index.empty:
        st.dataframe(index, use_container_width=True, hide_index=True)


def page_compliance() -> None:
    st.title("Retailer Audits")
    st.caption(
        "Module 2. Seven checks per SKU — S1, S2 on the listing tile and P1–P5 on "
        "the product page — rolled up **85% notebook / 15% desktop** per the brief."
    )
    data_source_banner()

    compliance = load_compliance()
    if compliance.empty:
        empty_state()
        return

    st.info(
        "**Unevaluable checks are excluded from the denominator, not scored as "
        "failures.** If a product page did not load, P1–P5 are unknowable — scoring "
        "them zero would blame a brand for our own collection gap. `Coverage %` "
        "reports how often that happened, so a low-confidence score is visibly "
        "low-confidence.",
        icon="ℹ️",
    )

    filtered, _ = platform_filter(compliance, "compliance_platform")
    tracked = filtered[filtered["brand"].isin(tracked_brands())]

    st.subheader("Brand Compliance Score")
    for platform, chunk in tracked.groupby("platform"):
        st.markdown(f"**{_platform_label(platform)}**")
        chunk = chunk.sort_values("compliance_score")
        st.plotly_chart(
            brand_bar(chunk, x="compliance_score", y="brand", suffix=" / 100"),
            use_container_width=True, key=f"compliance_{platform}",
        )
        low = chunk[chunk["low_confidence"]]
        if not low.empty:
            st.caption(
                "⚠️ Low coverage (<60%), treat with caution: "
                + ", ".join(brand_label(b) for b in low["brand"])
            )
    table_view(tracked, "Compliance scores — underlying data")

    st.divider()
    st.subheader("Per-check pass rates")
    st.caption(
        "Where compliance is actually breaking. S1/S2 are listing-page checks; "
        "P1–P5 are product-page checks."
    )
    detail = load_compliance_detail()
    if not detail.empty:
        detail = detail[detail["brand"].isin(tracked_brands())]
        pivot = (
            detail.groupby(["brand", "check_code"])
            .apply(lambda g: (g["passed"].sum() / g["evaluated"].sum() * 100)
                   if g["evaluated"].sum() else float("nan"), include_groups=False)
            .reset_index(name="pass_rate")
            .pivot(index="brand", columns="check_code", values="pass_rate")
        )
        order = ["S1", "S2", "P1", "P2", "P3", "P4", "P5"]
        pivot = pivot[[c for c in order if c in pivot.columns]]
        pivot.index = [brand_label(b) for b in pivot.index]

        fig = go.Figure(go.Heatmap(
            z=pivot.values, x=pivot.columns, y=pivot.index,
            colorscale=SEQUENTIAL_BLUE, zmin=0, zmax=100,
            xgap=2, ygap=2,
            text=[[f"{v:.0f}%" if v == v else "—" for v in row] for row in pivot.values],
            texttemplate="%{text}",
            textfont=dict(size=12, color=TEXT_PRIMARY),
            colorbar=dict(title="Pass %", thickness=12),
            hovertemplate="%{y} · %{x}: %{z:.1f}%<extra></extra>",
        ))
        st.plotly_chart(style(fig, height=90 + 46 * len(pivot), showlegend=False),
                        use_container_width=True, key="compliance_heat")

        legend = pd.DataFrame([
            ("S1", "Listing", "Title includes brand name and/or processor line"),
            ("S2", "Listing", "Badge shown on the listing tile"),
            ("P1", "Product", "Title includes brand, processor line, or generation"),
            ("P2", "Product", "Badge shown on the product page"),
            ("P3", "Product", "Brand or processor line named in the spec table"),
            ("P4", "Product", "Brand-led rich media present"),
            ("P5", "Product", "OEM rich media present"),
        ], columns=["Check", "Page", "What it verifies"])
        st.dataframe(legend, use_container_width=True, hide_index=True)
        table_view(detail, "Per-check detail — underlying data")


def page_shelf() -> None:
    st.title("Share of Shelf")
    st.caption(
        "Module 4. Percentage of listed gaming products per brand, trended over "
        "time — the core competitive-health metric."
    )
    data_source_banner()

    shelf = load_shelf()
    if shelf.empty:
        empty_state()
        return

    filtered, _ = platform_filter(shelf, "shelf_platform")

    st.subheader("Share over time")
    for platform, chunk in filtered.groupby("platform"):
        st.markdown(f"**{_platform_label(platform)}**")
        st.plotly_chart(
            brand_lines(chunk, x="date", y="share_pct", suffix="%"),
            use_container_width=True, key=f"shelftrend_{platform}",
        )
    table_view(filtered, "Share of Shelf — underlying data")

    st.divider()
    st.subheader("Shelf position")
    st.caption(
        "Share of Shelf alone can hide a real problem: a brand can hold 30% of "
        "listings while sitting at the bottom of every page. Median rank and "
        "top-10 presence make that visible."
    )
    position = core.shelf_position()
    if not position.empty:
        display = position.copy()
        display["brand"] = display["brand"].map(brand_label)
        display["platform"] = display["platform"].map(_platform_label)
        st.dataframe(
            display.rename(columns={
                "platform": "Platform", "brand": "Brand", "listings": "Listings",
                "median_rank": "Median rank", "best_rank": "Best rank",
                "top10_count": "In top 10", "top10_share_pct": "Top-10 share %",
                "sponsored_count": "Sponsored",
            }),
            use_container_width=True, hide_index=True,
        )


def page_voice() -> None:
    st.title("Share of Voice")
    st.caption(
        "Module 8. Rank-weighted visibility across a defined keyword set per "
        "country, plus home-page presence. Position 1 is worth far more than "
        "position 20, so ranks are discounted logarithmically (DCG) rather than "
        "counted."
    )
    data_source_banner()

    sov = load_sov()
    if sov.empty:
        empty_state()
        return

    st.caption(
        "Category (brand-neutral) keywords only. Branded keywords are reported "
        "separately below — a brand ranking first for its own name is expected and "
        "would drown out the contested terms."
    )
    filtered, _ = platform_filter(sov, "sov_platform")

    latest = filtered[filtered["date"] == filtered["date"].max()]
    for platform, chunk in latest.groupby("platform"):
        st.markdown(f"**{_platform_label(platform)}**")
        chunk = chunk.sort_values("sov_pct")
        st.plotly_chart(
            brand_bar(chunk, x="sov_pct", y="brand", suffix="%"),
            use_container_width=True, key=f"sov_{platform}",
        )
    table_view(filtered, "Share of Voice — underlying data")

    st.divider()
    st.subheader("Home-page presence")
    st.caption(
        "The other surface module 8 asks for: which brands hold the home page's "
        "featured product tiles, position-discounted the same way. Reported "
        "separately rather than blended into the number above — a homepage tile "
        "and a keyword rank are different kinds of visibility. Carousel banners "
        "are tracked separately again under Banner Tracking."
    )
    home = core.homepage_presence()
    if home.empty:
        st.info("No home-page product tiles recorded yet.")
    else:
        home_latest = home[home["date"] == home["date"].max()]
        for platform, chunk in home_latest.groupby("platform"):
            st.markdown(f"**{_platform_label(platform)}**")
            chunk = chunk.sort_values("presence_pct")
            st.plotly_chart(
                brand_bar(chunk, x="presence_pct", y="brand", suffix="%"),
                use_container_width=True, key=f"home_{platform}",
            )
        table_view(home, "Home-page presence — underlying data")

    st.divider()
    st.subheader("Keyword detail")
    st.caption("Which specific terms each brand wins or loses.")
    detail = core.keyword_detail()
    if not detail.empty:
        group = st.radio("Keyword group", ["category", "branded"],
                         horizontal=True, key="kw_group")
        subset = detail[detail["keyword_group"] == group].copy()
        subset["brand"] = subset["brand"].map(brand_label)
        subset["platform"] = subset["platform"].map(_platform_label)
        st.dataframe(
            subset.rename(columns={
                "platform": "Platform", "keyword": "Keyword", "brand": "Brand",
                "appearances": "Results", "best_rank": "Best rank",
                "median_rank": "Median rank", "sov_pct": "SoV %",
            }).drop(columns=["keyword_group", "dcg"], errors="ignore"),
            use_container_width=True, hide_index=True,
        )


def page_banners() -> None:
    st.title("Banner Tracking")
    st.caption(
        "Module 3. Homepage banner slots, captured daily. Banners carry no SKU, so "
        "attribution runs over alt text and link slug — weaker evidence than a "
        "product title, which is why confidence is shown rather than hidden."
    )
    data_source_banner()

    banner = load_banner()
    if banner.empty:
        empty_state()
        return

    filtered, _ = platform_filter(banner, "banner_platform")
    latest = filtered[filtered["date"] == filtered["date"].max()]

    st.subheader("Banner share")
    st.caption(
        "Raw share counts slots equally; weighted share discounts by position "
        "(1/position), because the hero slot is worth more than the fifth "
        "carousel tile. A brand with five tail slots is not beating one holding "
        "the hero."
    )
    for platform, chunk in latest.groupby("platform"):
        st.markdown(f"**{_platform_label(platform)}**")
        chunk = chunk.sort_values("weighted_share_pct")
        fig = go.Figure()
        labels = [brand_label(b) for b in chunk["brand"]]
        fig.add_trace(go.Bar(
            y=labels, x=chunk["share_pct"], orientation="h", name="Raw share",
            marker=dict(color=[brand_color(b) for b in chunk["brand"]],
                        line=dict(color=SURFACE, width=2), opacity=0.45),
            hovertemplate="%{y} raw: %{x:.1f}%<extra></extra>",
        ))
        fig.add_trace(go.Bar(
            y=labels, x=chunk["weighted_share_pct"], orientation="h",
            name="Position-weighted",
            marker=dict(color=[brand_color(b) for b in chunk["brand"]],
                        line=dict(color=SURFACE, width=2)),
            text=[f"{v:.1f}%" for v in chunk["weighted_share_pct"]],
            textposition="outside", textfont=dict(color=TEXT_PRIMARY),
            hovertemplate="%{y} weighted: %{x:.1f}%<extra></extra>",
        ))
        fig.update_traces(marker_cornerradius=4)
        fig.update_layout(barmode="group")
        st.plotly_chart(style(fig, height=max(240, 56 * len(chunk) + 60)),
                        use_container_width=True, key=f"banner_{platform}")
    table_view(filtered, "Banner share — underlying data")

    st.divider()
    st.subheader("Captured banner slots")
    raw = banners_frame()
    if not raw.empty:
        display = raw.sort_values(["observed_at", "slot_position"], ascending=[False, True])
        display = display.head(120).copy()
        display["brand"] = display["brand"].map(brand_label)
        display["platform"] = display["platform"].map(_platform_label)
        st.dataframe(
            display[["platform", "observed_at", "slot_position", "brand",
                     "brand_confidence", "alt_text", "link_url",
                     "has_discount", "discount_text"]].rename(columns={
                "platform": "Platform", "observed_at": "Observed",
                "slot_position": "Slot", "brand": "Brand",
                "brand_confidence": "Confidence", "alt_text": "Banner copy",
                "link_url": "Link", "has_discount": "Discount?",
                "discount_text": "Discount copy",
            }),
            use_container_width=True, hide_index=True,
        )


def page_badges() -> None:
    st.title("Badge Types & Relevance")
    st.caption(
        "Module 6. Detection is paired with **eligibility**: a compliance gap is a "
        "badge that is eligible *and* absent. A missing Intel Evo badge on a "
        "desktop is not a finding — Evo is a laptop-only certification."
    )
    data_source_banner()

    badges = load_badges()
    if badges.empty:
        empty_state()
        return

    filtered, _ = platform_filter(badges, "badge_platform")

    total_gaps = int(filtered["gap_count"].sum())
    total_eligible = int(filtered["eligible_count"].sum())
    misapplied = int(filtered["misapplied_count"].sum())

    c1, c2, c3 = st.columns(3)
    c1.metric("Eligible badge placements", f"{total_eligible:,}")
    c2.metric("Compliance gaps", f"{total_gaps:,}",
              f"{total_gaps / total_eligible * 100:.1f}% of eligible" if total_eligible else "")
    c3.metric("Misapplied badges", f"{misapplied:,}",
              help="Badge shown where it does not apply — a different conversation "
                   "with the retailer than a missing badge.")

    st.subheader("Badge compliance by brand and badge")
    display = filtered.copy()
    display["brand"] = display["brand"].map(brand_label)
    display["platform"] = display["platform"].map(_platform_label)
    st.dataframe(
        display.rename(columns={
            "platform": "Platform", "brand": "Brand", "badge_name": "Badge",
            "page_type": "Page", "eligible_count": "Eligible",
            "present_count": "Present", "gap_count": "Gaps",
            "misapplied_count": "Misapplied", "compliance_pct": "Compliance %",
            "skus": "SKUs",
        }),
        use_container_width=True, hide_index=True,
    )

    st.divider()
    st.subheader("Gap drill-down — SKUs missing an eligible badge")
    st.caption("The actionable list: each row is a specific product page to fix.")
    gaps = core.badge_gaps()
    if gaps.empty:
        st.success("No badge gaps detected.")
    else:
        gaps = gaps.copy()
        gaps["brand"] = gaps["brand"].map(brand_label)
        gaps["platform"] = gaps["platform"].map(_platform_label)
        st.dataframe(gaps, use_container_width=True, hide_index=True)


def page_sku_explorer() -> None:
    st.title("SKU Explorer")
    st.caption(
        "Module 7. Search, filter and drill into individual products, so every "
        "number elsewhere in this dashboard can be traced to the SKUs driving it."
    )
    data_source_banner()

    products = load_products()
    observations = load_observations()
    if products.empty:
        empty_state()
        return

    latest = (
        observations.sort_values("observed_at")
        .groupby("product_id", as_index=False)
        .last()[["product_id", "price_current", "price_was", "currency",
                 "discount_pct", "has_promo", "in_stock", "listing_rank",
                 "observed_at"]]
        if not observations.empty else pd.DataFrame(columns=["product_id"])
    )
    merged = products.merge(latest, on="product_id", how="left")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        platform = st.selectbox("Platform", ["All"] + sorted(merged["platform"].unique()),
                                format_func=_platform_label, key="sku_platform")
    with c2:
        brands = ["All"] + sorted(merged["brand"].unique())
        brand = st.selectbox("Brand", brands, format_func=lambda b: (
            "All brands" if b == "All" else brand_label(b)), key="sku_brand")
    with c3:
        oems = ["All"] + sorted(merged["oem"].dropna().unique())
        oem = st.selectbox("OEM", oems, format_func=lambda o: (
            "All OEMs" if o == "All" else str(o).title()), key="sku_oem")
    with c4:
        types = ["All"] + sorted(merged["product_type"].unique())
        ptype = st.selectbox("Product type", types, key="sku_type")

    query = st.text_input("Search titles", placeholder="e.g. Legion, Ryzen 7, MacBook",
                          key="sku_query")

    view = merged.copy()
    if platform != "All":
        view = view[view["platform"] == platform]
    if brand != "All":
        view = view[view["brand"] == brand]
    if oem != "All":
        view = view[view["oem"] == oem]
    if ptype != "All":
        view = view[view["product_type"] == ptype]
    if query:
        view = view[view["title"].str.contains(query, case=False, na=False)]

    st.caption(f"{len(view):,} SKU(s) match.")

    display = view.copy()
    display["brand"] = display["brand"].map(brand_label)
    display["platform"] = display["platform"].map(_platform_label)
    st.dataframe(
        display[[
            "platform", "brand", "oem", "product_type", "platform_sku", "title",
            "processor_line", "price_current", "currency", "discount_pct",
            "has_promo", "in_stock", "listing_rank", "brand_confidence",
            "brand_evidence", "is_delisted", "url",
        ]].rename(columns={
            "platform": "Platform", "brand": "Brand", "oem": "OEM",
            "product_type": "Type", "platform_sku": "SKU", "title": "Title",
            "processor_line": "Processor line", "price_current": "Price",
            "currency": "Currency", "discount_pct": "Discount %",
            "has_promo": "On promo", "in_stock": "In stock",
            "listing_rank": "Shelf rank", "brand_confidence": "Attr. confidence",
            "brand_evidence": "Attr. evidence", "is_delisted": "Delisted",
            "url": "URL",
        }),
        use_container_width=True, hide_index=True,
        column_config={"URL": st.column_config.LinkColumn("URL", display_text="open")},
    )

    st.divider()
    st.subheader("Price history for a single SKU")
    if not view.empty and not observations.empty:
        options = view["product_id"].tolist()
        chosen = st.selectbox(
            "SKU", options, key="sku_drill",
            format_func=lambda pid: str(
                view.loc[view["product_id"] == pid, "title"].iloc[0]
            )[:110],
        )
        history = observations[observations["product_id"] == chosen].sort_values("observed_at")
        if not history.empty:
            row = view[view["product_id"] == chosen].iloc[0]
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=history["observed_at"], y=history["price_current"],
                mode="lines+markers", name="Price",
                line=dict(color=brand_color(row["brand"]), width=2),
                marker=dict(size=8, line=dict(color=SURFACE, width=2)),
                hovertemplate="%{x}<br>%{y:,.2f}<extra></extra>",
            ))
            promos = history[history["has_promo"] == True]  # noqa: E712
            if not promos.empty:
                fig.add_trace(go.Scatter(
                    x=promos["observed_at"], y=promos["price_current"],
                    mode="markers", name="On promotion",
                    marker=dict(size=13, color=STATUS["warning"], symbol="circle",
                                line=dict(color=SURFACE, width=2)),
                    hovertemplate="Promo<br>%{x}<br>%{y:,.2f}<extra></extra>",
                ))
            st.plotly_chart(
                style(fig, y_title=f"Price ({row.get('currency', '')})"),
                use_container_width=True, key="sku_price_hist",
            )
            st.caption(
                f"**Attribution:** {brand_label(row['brand'])} "
                f"(confidence {row['brand_confidence']:.2f}, evidence: "
                f"`{row['brand_evidence']}`) · OEM: {row['oem'] or '—'}"
            )
            table_view(history, "Observation history for this SKU")


def page_competitiveness() -> None:
    st.title("Competitiveness Score")
    st.caption("Nice-to-have: a single rankable score per brand.")
    data_source_banner()

    st.warning(
        "**This is a constructed index, not an observation.** Its weights are a "
        "judgement call and different weights produce a different ranking. Treat it "
        "as a conversation starter — every pillar decomposes back to the measured "
        "numbers below, and it should never be quoted without them.",
        icon="⚠️",
    )

    scores = load_competitiveness()
    if scores.empty:
        empty_state()
        return

    st.code(score_explanation(), language=None)

    filtered, _ = platform_filter(scores, "comp_platform")
    for platform, chunk in filtered.groupby("platform"):
        st.markdown(f"**{_platform_label(platform)}**")
        chunk = chunk.sort_values("competitiveness_score")
        st.plotly_chart(
            brand_bar(chunk, x="competitiveness_score", y="brand"),
            use_container_width=True, key=f"comp_{platform}",
        )

        pillar_cols = [c for c in ("pillar_pricing", "pillar_visibility",
                                   "pillar_compliance") if c in chunk.columns]
        fig = go.Figure()
        for _, row in chunk.iterrows():
            fig.add_trace(go.Bar(
                name=brand_label(row["brand"]),
                x=[c.replace("pillar_", "").title() for c in pillar_cols],
                y=[row[c] for c in pillar_cols],
                marker=dict(color=brand_color(row["brand"]),
                            line=dict(color=SURFACE, width=2)),
                text=[f"{row[c]:.0f}" for c in pillar_cols],
                textposition="outside", textfont=dict(color=TEXT_PRIMARY, size=11),
                hovertemplate="%{fullData.name}<br>%{x}: %{y:.1f}<extra></extra>",
            ))
        fig.update_traces(marker_cornerradius=4)
        fig.update_layout(barmode="group", yaxis_range=[0, 118])
        st.plotly_chart(style(fig, y_title="Pillar score (0–100)"),
                        use_container_width=True, key=f"pillars_{platform}")

    table_view(filtered, "Competitiveness components — underlying data")


def page_alerts() -> None:
    st.title("Alerts & Change Flags")
    st.caption(
        "Nice-to-have. Each alert compares the two most recent usable runs. Alerts "
        "are deduplicated, so a price that dropped and stayed there is one event, "
        "not one per run."
    )
    data_source_banner()

    alerts = load_alerts()
    if alerts.empty:
        st.success("No alerts recorded.")
        return

    st.info(
        "Alerts never fire on our own collection gaps: a SKU absent because a fetch "
        "failed is not a delisting, and delisting requires three consecutive "
        "absences on healthy runs.",
        icon="ℹ️",
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        severity = st.multiselect("Severity", sorted(alerts["severity"].unique()),
                                  default=sorted(alerts["severity"].unique()))
    with c2:
        types = st.multiselect("Type", sorted(alerts["alert_type"].unique()))
    with c3:
        plat = st.selectbox("Platform", ["All"] + sorted(alerts["platform"].unique()),
                            format_func=_platform_label, key="alert_platform")

    view = alerts[alerts["severity"].isin(severity)] if severity else alerts
    if types:
        view = view[view["alert_type"].isin(types)]
    if plat != "All":
        view = view[view["platform"] == plat]

    counts = view.groupby("alert_type").size().reset_index(name="count")
    counts = counts.sort_values("count")
    if not counts.empty:
        severity_of = (
            view.groupby("alert_type")["severity"].agg(
                lambda s: s.mode().iloc[0] if not s.mode().empty else "low")
        )
        fig = go.Figure(go.Bar(
            x=counts["count"],
            y=[t.replace("_", " ").title() for t in counts["alert_type"]],
            orientation="h",
            marker=dict(
                color=[SEVERITY_COLORS.get(severity_of.get(t, "low"), STATUS["neutral"])
                       for t in counts["alert_type"]],
                line=dict(color=SURFACE, width=2),
            ),
            text=counts["count"], textposition="outside",
            textfont=dict(color=TEXT_PRIMARY),
            hovertemplate="%{y}: %{x}<extra></extra>",
        ))
        fig.update_traces(marker_cornerradius=4)
        st.plotly_chart(style(fig, showlegend=False,
                              height=max(240, 42 * len(counts) + 60)),
                        use_container_width=True, key="alert_counts")

    display = view.sort_values("created_at", ascending=False).copy()
    display["brand"] = display["brand"].fillna("—").map(
        lambda b: brand_label(b) if b != "—" else b)
    display["platform"] = display["platform"].map(_platform_label)
    st.dataframe(
        display[["created_at", "severity", "alert_type", "platform", "brand",
                 "message", "prev_value", "new_value", "delta"]].rename(columns={
            "created_at": "When", "severity": "Severity", "alert_type": "Type",
            "platform": "Platform", "brand": "Brand", "message": "Message",
            "prev_value": "Previous", "new_value": "Current", "delta": "Δ",
        }),
        use_container_width=True, hide_index=True,
    )


def page_data_quality() -> None:
    st.title("Data Quality & Run Log")
    st.caption(
        "Collection health. A dashboard that cannot show how its data was "
        "gathered cannot be trusted with a decision."
    )
    data_source_banner()

    runs = load_runs()
    if runs.empty:
        empty_state()
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total runs", f"{len(runs):,}")
    c2.metric("Usable", f"{int(runs['status'].isin(['ok', 'partial']).sum()):,}")
    c3.metric("Failed", f"{int((runs['status'] == 'failed').sum()):,}")
    c4.metric("Blocked fetches", f"{int(runs['blocked_count'].sum()):,}")

    st.subheader("Attribution confidence")
    st.caption(
        "Low-confidence rows are attributed from a bare brand mention rather than a "
        "processor line. They are kept — dropping them would bias Share of Shelf — "
        "but they are visible here so a reader can judge how much of a metric rests "
        "on weak evidence."
    )
    products = load_products()
    if not products.empty:
        conf = products.groupby(["platform", "brand"]).agg(
            skus=("product_id", "count"),
            avg_confidence=("brand_confidence", "mean"),
            low_confidence=("brand_confidence", lambda s: int((s < 0.6).sum())),
        ).reset_index()
        conf["avg_confidence"] = conf["avg_confidence"].round(2)
        conf["brand"] = conf["brand"].map(brand_label)
        conf["platform"] = conf["platform"].map(_platform_label)
        st.dataframe(conf.rename(columns={
            "platform": "Platform", "brand": "Brand", "skus": "SKUs",
            "avg_confidence": "Avg confidence", "low_confidence": "Low-confidence SKUs",
        }), use_container_width=True, hide_index=True)

    st.subheader("Run log")
    display = runs.sort_values("started_at", ascending=False).copy()
    display["platform"] = display["platform"].map(_platform_label)
    st.dataframe(
        display[["started_at", "platform", "run_type", "slot", "status",
                 "items_found", "items_parsed", "fetch_errors", "parse_errors",
                 "blocked_count", "notes"]].rename(columns={
            "started_at": "Started", "platform": "Platform", "run_type": "Module",
            "slot": "Slot", "status": "Status", "items_found": "Found",
            "items_parsed": "Parsed", "fetch_errors": "Fetch errors",
            "parse_errors": "Parse errors", "blocked_count": "Blocked",
            "notes": "Notes",
        }),
        use_container_width=True, hide_index=True,
    )


PAGES = {
    "Overview": page_overview,
    "Pricing & Promotions": page_pricing,
    "Retailer Audits": page_compliance,
    "Share of Shelf": page_shelf,
    "Share of Voice": page_voice,
    "Banner Tracking": page_banners,
    "Badges": page_badges,
    "SKU Explorer": page_sku_explorer,
    "Competitiveness": page_competitiveness,
    "Alerts": page_alerts,
    "Data Quality": page_data_quality,
}


def main() -> None:
    bootstrap_warehouse()

    with st.sidebar:
        st.markdown("### Retail Brand Benchmark")
        st.caption("Intel · AMD · Qualcomm · Apple  \nNewegg (US) · Mercado Libre (BR)")
        choice = st.radio("Section", list(PAGES), label_visibility="collapsed")
        st.divider()
        st.caption(
            "**Brand** = chip/SoC supplier (the axis every metric rolls up on).\n\n"
            "**OEM** = device maker (drill-down filter only).\n\n"
            "Apple appears in both — expected, not a double-count."
        )
        st.divider()
        if st.button("Refresh data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    PAGES[choice]()


main()
