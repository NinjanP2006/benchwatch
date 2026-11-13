"""Measure how well the detector works, using a pool of real timings.

A pool is collected once (`bot collect`): the same commit built with several
injected slowdowns, run on one machine for many rounds. Within a round every
variant runs back to back with its own run of the unmodified reference build,
exactly as base and head do in `bot compare`. (An earlier design ran all
variants round-robin against a single reference run; pairs that ended up
several runs apart were measurably noisier than real comparisons.)

Simulation then repeatedly draws N rounds from the pool and runs the real
statistics on them:

* aa-ref vs aa             -> same binary twice: any flag is a false positive
* injectX-ref vs injectX   -> a regression verdict detects an X% slowdown

This turns one long collection into thousands of virtual PR runs at any round
count, without thousands of CI jobs. Rounds are drawn without replacement, so
each virtual run is a set of N real, distinct, paired rounds.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from benchwatch import parse
from benchwatch.runner import REF_SUFFIX
from benchwatch.stats import Params, Verdict, classify, compare_pairs

AA = "aa"
POOL_META = "pool-meta.json"
POOL_CSV = "pool.csv"


def inject_label(pct: float) -> str:
    return "inject" + f"{pct:g}".replace(".", "p")


def variant_plan(inject_pcts: list[float], inject_var: str) -> tuple[dict[str, tuple[str, ...]], dict[str, float]]:
    """Variant label -> extra CMake args (on top of the reference build's), and
    label -> nominal slowdown (%). The A/A variant is the reference build itself."""
    variants: dict[str, tuple[str, ...]] = {AA: ()}
    effects: dict[str, float] = {AA: 0.0}
    for pct in inject_pcts:
        label = inject_label(pct)
        variants[label] = (f"-D{inject_var}={pct:g}",)
        effects[label] = pct
    return variants, effects


# ---- loading -----------------------------------------------------------------

@dataclass
class Pool:
    benchmarks: list[str]
    times: dict[str, np.ndarray]  # side -> (benchmark, round) real_time_ns; sides are label and label-ref
    effects: dict[str, float]     # label -> nominal slowdown %
    meta: dict

    @property
    def rounds(self) -> int:
        return next(iter(self.times.values())).shape[1]

    def pair(self, label: str) -> tuple[np.ndarray, np.ndarray]:
        """(reference, variant) times for one variant, rounds aligned."""
        return self.times[label + REF_SUFFIX], self.times[label]


def load_pool(pool_dir: Path, warmup: int = 1) -> Pool:
    meta = json.loads((pool_dir / POOL_META).read_text(encoding="utf-8"))
    csv = pool_dir / POOL_CSV
    df = pd.read_csv(csv) if csv.exists() else parse.load_run(pool_dir)
    df = df[df["round"] >= warmup]
    wide = df.pivot_table(index=["benchmark", "round"], columns="side", values="real_time_ns", aggfunc="first")
    wide = wide.dropna()  # keep only rounds where every variant produced a result

    benchmarks = list(dict.fromkeys(df["benchmark"]))
    benchmarks = [b for b in benchmarks if b in wide.index.get_level_values(0)]
    rounds = sorted(set.intersection(*(set(wide.loc[b].index) for b in benchmarks)))
    times = {label: np.array([wide.loc[b].loc[rounds, label].to_numpy() for b in benchmarks])
             for label in wide.columns}
    return Pool(benchmarks=benchmarks, times=times, effects=meta["effects"], meta=meta)


def measured_effects(pool: Pool) -> dict[str, float]:
    """Slowdown actually observed over the whole pool, in %: median over benchmarks
    of each benchmark's median per-round ratio against its paired reference."""
    out = {}
    for label in pool.effects:
        ref, var = pool.pair(label)
        out[label] = float(np.median(np.median(var / ref, axis=1)) - 1) * 100
    return out


# ---- simulation ------------------------------------------------------------------

def simulate(pool: Pool, rounds_list: list[int], thresholds: list[float], trials: int,
             alpha: float = 0.01, n_boot: int = 2000, seed: int = 0) -> pd.DataFrame:
    """One row per (variant, rounds, threshold, trial, benchmark) with the verdict.

    p-values and CIs don't depend on the threshold, so each virtual run is
    analysed once and then classified under every threshold.
    """
    rng = np.random.default_rng(seed)
    stats_params = Params(alpha=alpha, n_boot=n_boot)
    class_params = {t: Params(alpha=alpha, threshold=t) for t in thresholds}
    rows: list[tuple] = []
    for n in rounds_list:
        if n > pool.rounds:
            raise ValueError(f"{n} rounds requested but the pool has only {pool.rounds} usable rounds")
        for trial in range(trials):
            idx = rng.choice(pool.rounds, size=n, replace=False)
            for label in pool.effects:
                ref, head = pool.pair(label)
                pairs = [(b, ref[i, idx], head[i, idx]) for i, b in enumerate(pool.benchmarks)]
                for r in compare_pairs(pairs, stats_params, rng):
                    for t, p in class_params.items():
                        verdict = classify(r.p_adjusted, r.ci_low, r.ci_high, p)
                        rows.append((label, n, t, trial, r.benchmark, verdict.value))
    return pd.DataFrame(rows, columns=["variant", "rounds", "threshold", "trial", "benchmark", "verdict"])


def summarize(sim: pd.DataFrame, pool: Pool) -> pd.DataFrame:
    """Rates per (variant, rounds, threshold).

    *_rate columns are per benchmark per run. any_flag_rate is per run: the
    fraction of virtual runs where at least one benchmark was flagged, which
    for the A/A variant is the false-alarm rate a PR author would experience.
    """
    keys = ["variant", "rounds", "threshold"]
    out = sim.assign(**{f"{v.value}_rate": sim["verdict"].eq(v.value) for v in Verdict})
    rates = out.groupby(keys)[[f"{v.value}_rate" for v in Verdict]].mean()
    flagged = sim["verdict"].isin([Verdict.REGRESSION.value, Verdict.IMPROVEMENT.value])
    per_run = sim.assign(flag=flagged).groupby(keys + ["trial"])["flag"].any().groupby(keys).mean()
    summary = rates.join(per_run.rename("any_flag_rate")).reset_index()

    measured = measured_effects(pool)
    summary.insert(1, "nominal_pct", summary["variant"].map(pool.effects))
    summary.insert(2, "measured_pct", summary["variant"].map(measured))
    return summary.sort_values(["threshold", "nominal_pct", "rounds"]).reset_index(drop=True)


def per_benchmark(sim: pd.DataFrame) -> pd.DataFrame:
    rate = sim.assign(regression=sim["verdict"].eq(Verdict.REGRESSION.value),
                      flagged=sim["verdict"].isin([Verdict.REGRESSION.value, Verdict.IMPROVEMENT.value]))
    return (rate.groupby(["variant", "rounds", "threshold", "benchmark"])[["regression", "flagged"]]
            .mean().reset_index())


def headline(summary: pd.DataFrame, rounds: int, threshold: float, effect_pct: float = 5.0) -> str:
    sel = summary[(summary["rounds"] == rounds) & (summary["threshold"] == threshold)]
    det = sel[sel["nominal_pct"] == effect_pct]
    aa = sel[sel["variant"] == AA]
    if det.empty or aa.empty:
        return "headline unavailable: pool lacks the A/A or the requested effect size"
    d, fp = det.iloc[0], aa.iloc[0]
    return (f"With {rounds} rounds and a {threshold:.0%} threshold, Benchwatch flags an injected "
            f"{effect_pct:g}% slowdown (measured {d['measured_pct']:+.1f}%) in "
            f"{d['regression_rate']:.0%} of benchmark comparisons, while identical code is flagged "
            f"in {fp['any_flag_rate']:.1%} of runs ({fp['regression_rate'] + fp['improvement_rate']:.2%} "
            f"of benchmark comparisons).")
