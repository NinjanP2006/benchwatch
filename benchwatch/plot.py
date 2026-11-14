"""Validation charts (needs the `plot` extra: `uv sync --extra plot`).

Two panels rather than one dual-axis chart: detection power against slowdown
size, and the A/A false-alarm rate against round count. Round count is
ordered, so its lines use one blue ramp stepped light->dark (validated as an
ordinal ramp for both surfaces); light and dark images are rendered
separately for the README's <picture> element.
"""

from pathlib import Path

import pandas as pd

from benchwatch.validate import AA

THEMES = {
    "light": {
        "surface": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781",
        "grid": "#e1e0d9", "axis": "#c3c2b7", "bar": "#2a78d6",
        "ramp": ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"],
    },
    "dark": {
        "surface": "#1a1a19", "ink": "#f0efec", "ink2": "#c3c2b7", "muted": "#898781",
        "grid": "#2c2c2a", "axis": "#383835", "bar": "#3987e5",
        "ramp": ["#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4"],
    },
}


def render_history(benchmark: str, df: pd.DataFrame, changepoints, out: Path, theme: str = "light") -> None:
    """Median time per commit on main, the level of each segment between detected
    changepoints, and a marker at each changepoint."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    from benchwatch.changepoint import segment_levels
    from benchwatch.report import format_pct

    t = THEMES[theme]
    x = np.arange(len(df))
    us = df["median_ns"].to_numpy() / 1e3
    levels = segment_levels(us, changepoints)

    fig, ax = plt.subplots(figsize=(10, 4), dpi=200)
    fig.patch.set_facecolor(t["surface"])
    _style_axes(ax, t)

    ax.plot(x, levels, color=t["ink2"], linewidth=1.2, linestyle=(0, (4, 3)), drawstyle="steps-mid",
            label="Segment median")
    ax.plot(x, us, color=t["bar"], linewidth=1.5, marker="o", markersize=4.5,
            markeredgecolor=t["surface"], markeredgewidth=1.0, label="Median time per commit")
    top = float(max(us.max(), levels.max()))
    for c in changepoints:
        ax.axvline(c.index - 0.5, color=t["muted"], linewidth=1, linestyle=(0, (3, 3)))
        ax.annotate(f"level shift {format_pct(1 + c.shift)}", xy=(c.index - 0.5, top), xytext=(4, 6),
                    textcoords="offset points", fontsize=8.5, color=t["ink"], fontweight="bold")

    step = max(1, len(df) // 12)
    ax.set_xticks(x[::step])
    ax.set_xticklabels([s[:7] for s in df["sha"].iloc[::step]], fontsize=8, rotation=0)
    span = top - float(min(us.min(), levels.min()))
    ax.set_ylim(float(min(us.min(), levels.min())) - span * 0.3, top + span * 0.35)
    ax.set_ylabel("Median time (µs)", color=t["ink2"], fontsize=9.5)
    ax.set_xlabel("Commit on main (oldest → newest)", color=t["ink2"], fontsize=9.5)
    ax.set_title(f"{benchmark} over {len(df)} commits", loc="left", color=t["ink"], fontsize=11,
                 fontweight="bold", pad=12)
    legend = ax.legend(frameon=False, fontsize=8.5, loc="upper left")
    for text in legend.get_texts():
        text.set_color(t["ink2"])

    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=t["surface"])
    plt.close(fig)


def _style_axes(ax, t: dict) -> None:
    ax.set_facecolor(t["surface"])
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(t["axis"])
    ax.tick_params(colors=t["muted"], length=0, labelsize=9)
    ax.grid(axis="y", color=t["grid"], linewidth=0.8)
    ax.set_axisbelow(True)


def render(summary: pd.DataFrame, threshold: float, out: Path, theme: str = "light",
           fp_target: float = 0.02) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter

    t = THEMES[theme]
    sel = summary[summary["threshold"] == threshold]
    injected = sel[sel["nominal_pct"] > 0]
    aa = sel[sel["variant"] == AA].sort_values("rounds")
    rounds = sorted(sel["rounds"].unique())
    ramp = t["ramp"][-len(rounds):] if len(rounds) <= len(t["ramp"]) else t["ramp"]

    fig, (left, right) = plt.subplots(1, 2, figsize=(10, 4), dpi=200,
                                      gridspec_kw={"width_ratios": [1.6, 1]})
    fig.patch.set_facecolor(t["surface"])

    # Panel 1: detection rate vs injected slowdown, one line per round count.
    _style_axes(left, t)
    for color, n in zip(ramp, rounds):
        line = injected[injected["rounds"] == n].sort_values("nominal_pct")
        left.plot(line["nominal_pct"], line["regression_rate"], color=color, linewidth=1.5,
                  marker="o", markersize=5, markeredgecolor=t["surface"], markeredgewidth=1.2,
                  label=f"N = {n}", solid_capstyle="round")
    left.axvline(threshold * 100, color=t["muted"], linewidth=1, linestyle=(0, (3, 3)))
    left.annotate(f"{threshold:.0%} threshold", xy=(threshold * 100, 1.02), xycoords=("data", "axes fraction"),
                  ha="center", fontsize=8.5, color=t["ink2"])
    left.set_ylim(0, 1.05)
    left.yaxis.set_major_formatter(PercentFormatter(1.0))
    left.set_xticks(sorted(injected["nominal_pct"].unique()))
    left.xaxis.set_major_formatter(PercentFormatter(100, decimals=0))
    left.set_xlabel("Injected slowdown", color=t["ink2"], fontsize=9.5)
    left.set_title("Regressions detected (per benchmark)", loc="left", color=t["ink"], fontsize=11,
                   fontweight="bold", pad=18)
    handles, labels_ = left.get_legend_handles_labels()  # most rounds first, matching line order
    legend = left.legend(handles[::-1], labels_[::-1], frameon=False, fontsize=8.5, loc="center right",
                         title="Rounds", title_fontsize=8.5)
    for text in legend.get_texts():
        text.set_color(t["ink2"])
    legend.get_title().set_color(t["ink2"])

    # Panel 2: share of A/A runs with any false flag, against round count.
    _style_axes(right, t)
    labels = [str(n) for n in aa["rounds"]]
    bars = right.bar(labels, aa["any_flag_rate"], color=t["bar"], width=0.6)
    for bar, value in zip(bars, aa["any_flag_rate"]):
        right.annotate(f"{value:.1%}", xy=(bar.get_x() + bar.get_width() / 2, value), xytext=(0, 3),
                       textcoords="offset points", ha="center", fontsize=8.5, color=t["ink2"])
    right.axhline(fp_target, color=t["muted"], linewidth=1, linestyle=(0, (3, 3)))
    right.annotate(f"{fp_target:.0%} target", xy=(1.0, fp_target), xycoords=("axes fraction", "data"),
                   xytext=(0, 3), textcoords="offset points", ha="right", fontsize=8.5, color=t["ink2"])
    top = max(fp_target * 2, float(aa["any_flag_rate"].max()) * 1.3, 0.01)
    right.set_ylim(0, top)
    right.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=1))
    right.set_xlabel("Rounds", color=t["ink2"], fontsize=9.5)
    right.set_title("False alarms (A/A runs)", loc="left", color=t["ink"], fontsize=11,
                    fontweight="bold", pad=18)

    fig.tight_layout(w_pad=3)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=t["surface"])
    plt.close(fig)
