"""Chart theme: fixed brand palette and Plotly styling.

Colour follows the *entity*, never its rank. BRAND_COLORS is a fixed map, so
filtering the view from six brands to three never repaints the survivors — a
reader who has learned "orange is AMD" keeps that across every chart and every
filter state.

Why not brand-true colours (Intel blue, AMD red, NVIDIA green)? They do not
survive as a set: Intel's and Qualcomm's brand blues are near-identical, and
Apple's grey falls below the chroma floor, so several pairs would be
indistinguishable — and AMD-red against NVIDIA-green is the textbook
red/green CVD collision. This palette was validated instead with the
dataviz validator in both light and dark mode (all checks pass; light mode
returns a contrast WARN, which is why every chart here ships direct labels
and a table view).
"""

from __future__ import annotations

import plotly.graph_objects as go

# Categorical slots, assigned in fixed order. Tracked brands take the leading
# slots because they are the ones that must stay separable.
BRAND_COLORS: dict[str, str] = {
    "intel": "#2a78d6",      # slot 1 blue
    "amd": "#eb6834",        # slot 2 orange
    "qualcomm": "#1baf7a",   # slot 3 aqua
    "apple": "#eda100",      # slot 4 yellow
    "nvidia": "#e87ba4",     # slot 5 magenta
    "mediatek": "#008300",   # slot 6 green
    # "other" is a residual bucket, not a competitor. Neutral grey says so and
    # keeps it from reading as a fifth tracked brand.
    "other": "#8c8b85",
    "unknown": "#8c8b85",
}

BRAND_LABELS: dict[str, str] = {
    "intel": "Intel",
    "amd": "AMD",
    "qualcomm": "Qualcomm",
    "apple": "Apple",
    "nvidia": "NVIDIA",
    "mediatek": "MediaTek",
    "other": "Other / unattributed",
    "unknown": "Unknown",
}

# Sequential ramp (single hue, light -> dark) for magnitude encodings such as
# the compliance heatmap. Starts at step 250 so the lightest cell still clears
# 2:1 against a light surface.
SEQUENTIAL_BLUE = [
    [0.0, "#86b6ef"],
    [0.25, "#5598e7"],
    [0.5, "#2a78d6"],
    [0.75, "#1c5cab"],
    [1.0, "#104281"],
]

# Status colours, reserved — never reused as a series hue.
STATUS = {
    "good": "#1baf7a",
    "warning": "#eda100",
    "serious": "#eb6834",
    "critical": "#e34948",
    "neutral": "#8c8b85",
}

SEVERITY_COLORS = {
    "high": STATUS["critical"],
    "medium": STATUS["warning"],
    "low": STATUS["neutral"],
}

TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID = "#e6e5e1"
SURFACE = "#ffffff"


def brand_color(brand: str) -> str:
    return BRAND_COLORS.get(str(brand).lower(), STATUS["neutral"])


def brand_label(brand: str) -> str:
    return BRAND_LABELS.get(str(brand).lower(), str(brand).title())


def color_map(brands) -> dict[str, str]:
    return {b: brand_color(b) for b in brands}


def style(fig: go.Figure, *, height: int = 380, showlegend: bool = True,
         y_title: str = "", x_title: str = "") -> go.Figure:
    """Apply recessive chrome: thin marks, quiet grid, legend above the plot."""
    fig.update_layout(
        height=height,
        showlegend=showlegend,
        margin=dict(l=8, r=8, t=48 if showlegend else 16, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif",
                  size=12, color=TEXT_SECONDARY),
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="left", x=0, title_text=""),
        hoverlabel=dict(font_size=12),
        hovermode="closest",
    )
    fig.update_xaxes(
        title_text=x_title, showgrid=False, zeroline=False,
        linecolor=GRID, tickcolor=GRID, color=TEXT_SECONDARY,
    )
    fig.update_yaxes(
        title_text=y_title, gridcolor=GRID, zeroline=False,
        linecolor="rgba(0,0,0,0)", tickcolor="rgba(0,0,0,0)", color=TEXT_SECONDARY,
    )
    return fig


def brand_bar(df, *, x: str, y: str, orientation: str = "h",
              text_fmt: str = "{:.1f}", suffix: str = "") -> go.Figure:
    """Horizontal bar with direct value labels.

    Direct labels are not decoration here: the light-mode palette returns a
    contrast WARN, and visible labels are the required relief.
    """
    fig = go.Figure()
    labels = [brand_label(b) for b in df[y]]
    fig.add_trace(go.Bar(
        x=df[x], y=labels, orientation=orientation,
        marker=dict(color=[brand_color(b) for b in df[y]],
                    line=dict(color=SURFACE, width=2)),
        text=[f"{text_fmt.format(v)}{suffix}" if v == v else "—" for v in df[x]],
        textposition="outside",
        textfont=dict(color=TEXT_PRIMARY, size=12),
        hovertemplate="%{y}: %{x}" + suffix + "<extra></extra>",
        showlegend=False,
    ))
    fig.update_traces(marker_cornerradius=4)
    fig = style(fig, showlegend=False, height=max(220, 46 * len(df) + 60))
    # Outside labels on the longest bar get clipped at the plot edge. These
    # labels are the contrast relief the palette requires, so headroom is not
    # cosmetic — without it the largest value is the one you cannot read.
    values = [v for v in df[x] if v == v]
    if values:
        # Headroom scales with label length: " / 100" needs far more room than
        # "%", and a fixed multiplier clips exactly the largest bar.
        sample = f"{text_fmt.format(max(values))}{suffix}"
        fig.update_xaxes(range=[0, max(values) * (1.10 + 0.028 * len(sample))])
    return fig


def brand_lines(df, *, x: str, y: str, group: str = "brand",
                suffix: str = "") -> go.Figure:
    """Multi-series line chart, one line per brand, with a legend."""
    fig = go.Figure()
    for brand, chunk in df.groupby(group):
        chunk = chunk.sort_values(x)
        fig.add_trace(go.Scatter(
            x=chunk[x], y=chunk[y], mode="lines+markers",
            name=brand_label(brand),
            line=dict(color=brand_color(brand), width=2),
            marker=dict(size=8, line=dict(color=SURFACE, width=2)),
            hovertemplate="%{fullData.name}<br>%{x}: %{y:.2f}" + suffix + "<extra></extra>",
        ))
    return style(fig)
