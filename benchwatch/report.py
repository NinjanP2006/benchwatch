"""Render an Analysis for the terminal and as JSON."""

import math
from dataclasses import asdict

from rich.console import Console
from rich.table import Table

from benchwatch.stats import Analysis, Verdict

_VERDICT_STYLE = {
    Verdict.REGRESSION: "bold red",
    Verdict.IMPROVEMENT: "bold green",
    Verdict.UNCHANGED: "dim",
    Verdict.INCONCLUSIVE: "yellow",
}


def format_time(ns: float) -> str:
    for unit, scale in (("s", 1e9), ("ms", 1e6), ("us", 1e3)):
        if ns >= scale:
            return f"{ns / scale:.3g} {unit}"
    return f"{ns:.3g} ns"


def format_pct(ratio: float) -> str:
    if not math.isfinite(ratio):
        return "n/a"
    return f"{(ratio - 1) * 100:+.1f}%"


def format_p(p: float) -> str:
    return "<0.001" if p < 0.001 else f"{p:.3f}"


def summary_line(analysis: Analysis) -> str:
    parts = [f"{analysis.count(v)} {v.value}" for v in Verdict if analysis.count(v)]
    return ", ".join(parts) if parts else "no benchmarks compared"


def render(analysis: Analysis, console: Console, title: str | None = None) -> None:
    p = analysis.params
    table = Table(title=title, title_justify="left")
    table.add_column("Benchmark")
    table.add_column("Base", justify="right")
    table.add_column("Head", justify="right")
    table.add_column("Change", justify="right")
    table.add_column(f"{p.confidence:.0%} CI", justify="right")
    table.add_column("p (Holm)", justify="right")
    table.add_column("n", justify="right")
    table.add_column("Verdict")

    for r in analysis.results:
        style = _VERDICT_STYLE[r.verdict]
        table.add_row(
            r.benchmark,
            format_time(r.base_median_ns),
            format_time(r.head_median_ns),
            format_pct(r.ratio),
            f"[{format_pct(r.ci_low)}, {format_pct(r.ci_high)}]",
            format_p(r.p_adjusted),
            str(r.n) + (f" ({r.outliers}!)" if r.outliers else ""),
            f"[{style}]{r.verdict.value}[/]",
        )
    console.print(table)
    console.print(f"[bold]{summary_line(analysis)}[/]  "
                  f"(alpha={p.alpha}, threshold=+/-{p.threshold:.0%}, warmup={p.warmup})")
    if any(r.outliers for r in analysis.results):
        console.print("[dim](k!) = k outlier rounds (>5 MAD from median), kept in the analysis[/]")
    for name in analysis.only_in_base:
        console.print(f"[yellow]removed in head:[/] {name}")
    for name in analysis.only_in_head:
        console.print(f"[yellow]new in head:[/] {name}")
    for w in analysis.warnings:
        console.print(f"[bold yellow]warning:[/] {w}")


def to_dict(analysis: Analysis) -> dict:
    def clean(x):
        return None if isinstance(x, float) and not math.isfinite(x) else x

    return {
        "params": asdict(analysis.params),
        "summary": {v.value: analysis.count(v) for v in Verdict},
        "results": [{k: clean(v.value if isinstance(v, Verdict) else v) for k, v in asdict(r).items()}
                    for r in analysis.results],
        "only_in_base": analysis.only_in_base,
        "only_in_head": analysis.only_in_head,
        "warnings": analysis.warnings,
    }
