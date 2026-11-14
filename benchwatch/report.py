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


# ---- Markdown (PR comment) ---------------------------------------------------

MARKER = "<!-- benchwatch -->"  # identifies our comment so updates replace it

_VERDICT_ICON = {
    Verdict.REGRESSION: "🔴",
    Verdict.IMPROVEMENT: "🟢",
    Verdict.UNCHANGED: "⚪",
    Verdict.INCONCLUSIVE: "🟡",
}


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _markdown_table(results) -> list[str]:
    lines = ["| Benchmark | Base | Head | Change | 95% CI | Verdict |",
             "|---|--:|--:|--:|--:|---|"]
    for r in results:
        lines.append(f"| `{r.benchmark}` | {format_time(r.base_median_ns)} | {format_time(r.head_median_ns)} "
                     f"| **{format_pct(r.ratio)}** | {format_pct(r.ci_low)} to {format_pct(r.ci_high)} "
                     f"| {_VERDICT_ICON[r.verdict]} {r.verdict.value} |")
    return lines


def to_markdown(analysis: Analysis, meta: dict | None = None, context: dict | None = None) -> str:
    p = analysis.params
    regressions = analysis.regressions
    improvements = [r for r in analysis.results if r.verdict is Verdict.IMPROVEMENT]
    others = [r for r in analysis.results if r.verdict in (Verdict.UNCHANGED, Verdict.INCONCLUSIVE)]

    if regressions:
        headline = f"🔴 {_plural(len(regressions), 'regression')}"
    elif improvements:
        headline = f"🟢 No regressions, {_plural(len(improvements), 'improvement')}"
    else:
        headline = "✅ No significant changes"

    lines = [MARKER, f"### Benchwatch: {headline}", ""]
    if meta:
        lines.append(f"Base `{meta['base']['sha'][:7]}` vs head `{meta['head']['sha'][:7]}` · "
                     f"{meta['config']['rounds']} interleaved rounds · threshold ±{p.threshold:.0%} · "
                     f"α = {p.alpha}")
        lines.append("")

    if regressions or improvements:
        lines += _markdown_table(regressions + improvements) + [""]

    if others:
        counts = ", ".join(f"{analysis.count(v)} {v.value}" for v in (Verdict.UNCHANGED, Verdict.INCONCLUSIVE)
                           if analysis.count(v))
        lines += ["<details>", f"<summary>{_plural(len(others), 'other benchmark')} ({counts})</summary>", ""]
        lines += _markdown_table(others) + ["", "</details>", ""]

    for name in analysis.only_in_base:
        lines.append(f"- Removed in head: `{name}`")
    for name in analysis.only_in_head:
        lines.append(f"- New in head: `{name}`")
    for w in analysis.warnings:
        lines.append(f"> [!WARNING]\n> {w}")
    if analysis.only_in_base or analysis.only_in_head or analysis.warnings:
        lines.append("")

    lines += ["<details>", "<summary>How to read this</summary>", "",
              f"Each round runs base and head back to back on the same machine. **Change** is the median "
              f"of the per-round head/base time ratios, with a bootstrap {p.confidence:.0%} confidence interval. "
              f"A **regression** must be statistically significant (Wilcoxon signed-rank, Holm-corrected "
              f"across all benchmarks, p < {p.alpha}) *and* have its whole CI more than {p.threshold:.0%} slower. "
              f"**Inconclusive** means the run was too noisy to rule a {p.threshold:.0%} change in or out.", ""]
    if meta or context:
        host = (meta or {}).get("host", {})
        ctx = context or {}
        cpu = f"{ctx.get('num_cpus', '?')} CPUs @ {ctx.get('mhz_per_cpu', '?')} MHz" if ctx else "unknown CPU"
        lines.append(f"Runner: {cpu}, {host.get('platform', 'unknown platform')}.")
        if meta:
            lines.append(f"Commits: base `{meta['base']['sha']}`, head `{meta['head']['sha']}`.")
        lines.append("")
    lines.append("</details>")
    return "\n".join(lines) + "\n"


def status_summary(analysis: Analysis) -> str:
    """Short (<=140 char) text for the commit status."""
    regressions = sorted(analysis.regressions, key=lambda r: r.ratio, reverse=True)
    if regressions:
        worst = regressions[0]
        text = f"{_plural(len(regressions), 'regression')}; worst {worst.benchmark} {format_pct(worst.ratio)}"
    else:
        text = f"No regressions across {_plural(len(analysis.results), 'benchmark')}"
    return text[:140]


# ---- Validation results ------------------------------------------------------------

def _validation_rows(summary) -> tuple[list[int], list[tuple[str, list[str]]]]:
    """Rows of (label, cells per round count) for one threshold's summary."""
    rounds = sorted(summary["rounds"].unique())
    rows: list[tuple[str, list[str]]] = []

    def cells(sel, column):
        by_n = sel.set_index("rounds")[column]
        return [f"{by_n[n]:.1%}" for n in rounds]

    for variant, sel in summary.groupby("variant", sort=False):
        first = sel.iloc[0]
        if first["nominal_pct"] == 0:
            measured = f"{first['measured_pct']:+.1f}%"
            rows.append((f"A/A ({measured}): runs with any false flag", cells(sel, "any_flag_rate")))
            rows.append(("A/A: benchmarks inconclusive", cells(sel, "inconclusive_rate")))
        else:
            rows.append((f"+{first['nominal_pct']:g}% injected ({first['measured_pct']:+.1f}% measured): "
                         f"flagged as regression", cells(sel, "regression_rate")))
    return rounds, rows


def render_validation(summary, console: Console, threshold: float) -> None:
    rounds, rows = _validation_rows(summary)
    table = Table(title=f"threshold ±{threshold:.0%}".replace("±", "+/-"), title_justify="left")
    table.add_column("Variant")
    for n in rounds:
        table.add_column(f"N={n}", justify="right")
    for label, values in rows:
        table.add_row(label, *values)
    console.print(table)


def validation_markdown(summary, pool, headline: str, trials: int, alpha: float, warmup: int) -> str:
    meta = pool.meta
    cfg = meta.get("config", {})
    lines = ["# Validation report", "", f"**{headline}**", "",
             f"Pool: commit `{meta['sha'][:7]}`, {len(pool.benchmarks)} benchmarks, {pool.rounds} usable rounds "
             f"(after {warmup} warmup), collected {meta.get('started_at', '?')} on "
             f"{meta.get('host', {}).get('platform', '?')}"
             + (f", pinned to CPU {cfg['cpu']}" if cfg.get("cpu") else "") + ".",
             f"Each cell is the mean over {trials} virtual runs of N rounds drawn without replacement "
             f"from the pool; α = {alpha} family-wise (Holm).", "",
             "Rows with injected slowdowns give the per-benchmark detection rate. The A/A rows compare "
             "two runs of the identical binary: *any false flag* is the share of virtual PR runs in which "
             "at least one benchmark was wrongly flagged.", ""]
    for t, sel in summary.groupby("threshold"):
        rounds, rows = _validation_rows(sel)
        lines += [f"## Threshold ±{t:.0%}", "",
                  "| | " + " | ".join(f"N={n}" for n in rounds) + " |",
                  "|---|" + "--:|" * len(rounds)]
        lines += [f"| {label} | " + " | ".join(values) + " |" for label, values in rows]
        lines.append("")
    return "\n".join(lines)


# ---- History -------------------------------------------------------------------------

def render_history(benchmark: str, df, changepoints, console: Console) -> None:
    starts = {c.index: c for c in changepoints}
    table = Table(title=f"{benchmark} on main", title_justify="left")
    for col, justify in (("Committed", "left"), ("Commit", "left"), ("Time", "right"),
                         ("vs parent", "right"), ("Verdict", "left"), ("", "left")):
        table.add_column(col, justify=justify)
    for i, row in enumerate(df.itertuples()):
        verdict = Verdict(row.verdict)
        mark = ""
        if i in starts:
            c = starts[i]
            mark = f"[bold magenta]<- level shift {format_pct(1 + c.shift)}[/]"
        table.add_row(row.committed_at[:10], row.sha[:7], format_time(row.median_ns),
                      format_pct(row.ratio_vs_parent), f"[{_VERDICT_STYLE[verdict]}]{verdict.value}[/]", mark)
    console.print(table)
    if not changepoints:
        console.print("no level shifts detected")
    for c in changepoints:
        console.print(f"level shift at {df['sha'].iloc[c.index][:7]}: {format_time(c.before_median)} -> "
                      f"{format_time(c.after_median)} ({format_pct(1 + c.shift)}, p={format_p(c.p_value)})")


def render_history_summary(series: dict, console: Console) -> None:
    table = Table(title="Benchmarks on main", title_justify="left")
    for col, justify in (("Benchmark", "left"), ("Commits", "right"), ("First", "right"),
                         ("Latest", "right"), ("Level shifts", "left")):
        table.add_column(col, justify=justify)
    for name, (df, cps) in series.items():
        shifts = ", ".join(f"[bold magenta]{format_pct(1 + c.shift)}[/] at {df['sha'].iloc[c.index][:7]}"
                           for c in cps) or "[dim]none[/]"
        table.add_row(name, str(len(df)), format_time(df["median_ns"].iloc[0]),
                      format_time(df["median_ns"].iloc[-1]), shifts)
    console.print(table)


def to_dict(analysis: Analysis) -> dict:
    def clean(x):
        return None if isinstance(x, float) and not math.isfinite(x) else x

    return {
        "params": asdict(analysis.params),
        "summary": {v.value: analysis.count(v) for v in Verdict},
        "status_description": status_summary(analysis),
        "results": [{k: clean(v.value if isinstance(v, Verdict) else v) for k, v in asdict(r).items()}
                    for r in analysis.results],
        "only_in_base": analysis.only_in_base,
        "only_in_head": analysis.only_in_head,
        "warnings": analysis.warnings,
    }
