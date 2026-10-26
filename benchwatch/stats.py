"""Per-benchmark significance test, effect size, and verdict.

Because base and head are interleaved, each round yields a matched pair, and
the per-round ratio head/base cancels most machine drift. We therefore work on
paired ratios:

* Effect size: median of the per-round ratios, with a bootstrap CI.
* Significance: Wilcoxon signed-rank test on log(ratio), which asks whether
  the ratios are centred on 1 without assuming normality (timings are skewed).
* Multiple comparisons: Holm correction across all benchmarks, so `alpha` is
  the chance of *any* false alarm in a run, not per benchmark.

A verdict needs both statistical significance and a practically large effect:
regression means "significant, and even the optimistic end of the CI is more
than `threshold` slower".
"""

import math
import warnings
from dataclasses import dataclass, field
from enum import Enum

import numpy as np
import pandas as pd
from scipy import stats as sps


class Verdict(str, Enum):
    REGRESSION = "regression"
    IMPROVEMENT = "improvement"
    UNCHANGED = "unchanged"        # CI rules out a change as large as the threshold
    INCONCLUSIVE = "inconclusive"  # too noisy to say either way


@dataclass(frozen=True)
class Params:
    alpha: float = 0.01
    threshold: float = 0.03
    warmup: int = 1
    confidence: float = 0.95
    n_boot: int = 10_000
    seed: int = 0


@dataclass
class BenchmarkResult:
    benchmark: str
    n: int
    base_median_ns: float
    head_median_ns: float
    ratio: float
    ci_low: float
    ci_high: float
    p_value: float
    p_adjusted: float
    outliers: int
    verdict: Verdict


@dataclass
class Analysis:
    params: Params
    results: list[BenchmarkResult]
    only_in_base: list[str] = field(default_factory=list)
    only_in_head: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def count(self, verdict: Verdict) -> int:
        return sum(r.verdict is verdict for r in self.results)

    @property
    def regressions(self) -> list[BenchmarkResult]:
        return [r for r in self.results if r.verdict is Verdict.REGRESSION]


def holm(p_values: list[float]) -> list[float]:
    """Holm-Bonferroni adjusted p-values (step-down, monotone, capped at 1)."""
    m = len(p_values)
    order = sorted(range(m), key=lambda i: p_values[i])
    adjusted = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * p_values[i]))
        adjusted[i] = running
    return adjusted


def bootstrap_median_ci(values: np.ndarray, confidence: float, n_boot: int,
                        rng: np.random.Generator) -> tuple[float, float]:
    idx = rng.integers(0, len(values), size=(n_boot, len(values)))
    medians = np.median(values[idx], axis=1)
    tail = (1 - confidence) / 2
    low, high = np.quantile(medians, [tail, 1 - tail])
    return float(low), float(high)


def signed_rank_p(log_ratios: np.ndarray) -> float:
    if np.all(log_ratios == 0):
        return 1.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # small-sample and tie warnings
        return float(sps.wilcoxon(log_ratios, alternative="two-sided").pvalue)


def count_outliers(log_ratios: np.ndarray, k: float = 5.0) -> int:
    """Rounds more than k robust standard deviations from the median. Reported, not dropped."""
    med = np.median(log_ratios)
    mad = 1.4826 * np.median(np.abs(log_ratios - med))
    return 0 if mad == 0 else int(np.sum(np.abs(log_ratios - med) > k * mad))


def min_rounds_for(m: int, alpha: float) -> int:
    """Smallest n with the exact signed-rank test's floor 2/2^n below alpha/m."""
    return math.ceil(math.log2(2 * m / alpha))


def classify(p_adjusted: float, ci_low: float, ci_high: float, params: Params) -> Verdict:
    significant = p_adjusted < params.alpha
    if significant and ci_low > 1 + params.threshold:
        return Verdict.REGRESSION
    if significant and ci_high < 1 - params.threshold:
        return Verdict.IMPROVEMENT
    if 1 - params.threshold <= ci_low and ci_high <= 1 + params.threshold:
        return Verdict.UNCHANGED
    return Verdict.INCONCLUSIVE


def paired_times(df: pd.DataFrame, warmup: int) -> pd.DataFrame:
    """Rows (benchmark, round) with base/head columns; drops warmup rounds and unpaired rounds."""
    df = df[df["round"] >= warmup]
    wide = df.pivot_table(index=["benchmark", "round"], columns="side", values="real_time_ns", aggfunc="first")
    return wide.dropna(subset=[c for c in ("base", "head") if c in wide.columns])


def analyze(df: pd.DataFrame, params: Params = Params()) -> Analysis:
    rng = np.random.default_rng(params.seed)
    order = list(dict.fromkeys(df["benchmark"]))  # suite order, as first seen
    sides = df.groupby("side")["benchmark"].unique()
    in_base = set(sides.get("base", []))
    in_head = set(sides.get("head", []))
    common = [b for b in order if b in in_base and b in in_head]

    analysis = Analysis(
        params=params,
        results=[],
        only_in_base=[b for b in order if b in in_base - in_head],
        only_in_head=[b for b in order if b in in_head - in_base],
    )
    if not common:
        analysis.warnings.append("no benchmarks present on both sides")
        return analysis

    wide = paired_times(df[df["benchmark"].isin(common)], params.warmup)
    raw: list[dict] = []
    for name in common:
        if name not in wide.index.get_level_values(0):
            continue
        pairs = wide.loc[name]
        base, head = pairs["base"].to_numpy(), pairs["head"].to_numpy()
        ratios = head / base
        log_ratios = np.log(ratios)
        n = len(ratios)
        if n >= 2:
            ci_low, ci_high = bootstrap_median_ci(ratios, params.confidence, params.n_boot, rng)
            p = signed_rank_p(log_ratios)
        else:
            ci_low, ci_high, p = -math.inf, math.inf, 1.0
        raw.append(dict(benchmark=name, n=n, base_median_ns=float(np.median(base)),
                        head_median_ns=float(np.median(head)), ratio=float(np.median(ratios)),
                        ci_low=ci_low, ci_high=ci_high, p_value=p, outliers=count_outliers(log_ratios)))

    for r, p_adj in zip(raw, holm([r["p_value"] for r in raw])):
        verdict = classify(p_adj, r["ci_low"], r["ci_high"], params)
        analysis.results.append(BenchmarkResult(**r, p_adjusted=p_adj, verdict=verdict))

    n_min = min(r.n for r in analysis.results)
    needed = min_rounds_for(len(analysis.results), params.alpha)
    if n_min < needed:
        analysis.warnings.append(
            f"only {n_min} usable rounds for {len(analysis.results)} benchmarks: no result can reach "
            f"significance at alpha={params.alpha}. Use at least {needed + params.warmup} rounds "
            f"({needed} + {params.warmup} warmup)."
        )
    return analysis
