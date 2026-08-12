"""Chart theme: fixed brand palette and Plotly styling."""

from __future__ import annotations

import plotly.graph_objects as go

BRAND_COLORS: dict[str, str] = {
    "intel": "#2a78d6",
    "amd": "#eb6834",
    "qualcomm": "#1baf7a",
    "apple": "#eda100",
    "nvidia": "#e87ba4",
    "mediatek": "#008300",
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

SEQUENTIAL_BLUE = [
    [0.0, "#86b6ef"],
    [0.25, "#5598e7"],
    [0.5, "#2a78d6"],
    [0.75, "#1c5cab"],
    [1.0, "#104281"],
]

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
    """Horizontal bar with direct value labels."""
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
    values = [v for v in df[x] if v == v]
    if values:
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
