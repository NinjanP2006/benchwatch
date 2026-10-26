import numpy as np
import pandas as pd
import pytest

from benchwatch.stats import Params, Verdict, analyze, classify, holm, min_rounds_for


def synthetic_run(effects: dict[str, float], rounds: int = 15, noise: float = 0.01,
                  drift: float = 0.0, seed: int = 1) -> pd.DataFrame:
    """Lognormal timings; `effects` maps benchmark -> true head/base ratio.

    `drift` adds a per-round multiplicative factor shared by base and head,
    like a machine slowly heating up. Pairing should cancel it.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for name, effect in effects.items():
        for r in range(rounds):
            shared = np.exp(drift * r)
            for side, mult in (("base", 1.0), ("head", effect)):
                t = 1000.0 * mult * shared * np.exp(rng.normal(0, noise))
                rows.append(dict(benchmark=name, side=side, round=r, real_time_ns=t,
                                 cpu_time_ns=t, iterations=100))
    return pd.DataFrame(rows)


def verdicts(analysis):
    return {r.benchmark: r.verdict for r in analysis.results}


def test_detects_regression_and_improvement_among_unchanged():
    df = synthetic_run({"slow": 1.10, "fast": 0.90, "same1": 1.0, "same2": 1.0})
    v = verdicts(analyze(df))
    assert v["slow"] is Verdict.REGRESSION
    assert v["fast"] is Verdict.IMPROVEMENT
    assert v["same1"] is Verdict.UNCHANGED
    assert v["same2"] is Verdict.UNCHANGED


def test_effect_size_and_ci_cover_true_ratio():
    result = analyze(synthetic_run({"b": 1.07})).results[0]
    assert result.ratio == pytest.approx(1.07, abs=0.01)
    assert result.ci_low < 1.07 < result.ci_high


def test_small_significant_change_below_threshold_is_not_a_regression():
    # 1% slower with tiny noise: statistically real but below the 3% bar.
    result = analyze(synthetic_run({"b": 1.01}, noise=0.001)).results[0]
    assert result.p_adjusted < 0.01
    assert result.verdict is Verdict.UNCHANGED


def test_noisy_benchmark_is_inconclusive_not_flagged():
    result = analyze(synthetic_run({"b": 1.05}, noise=0.25)).results[0]
    assert result.verdict is Verdict.INCONCLUSIVE


def test_pairing_cancels_shared_drift():
    # 30% drift over the run would swamp a 5% effect if rounds were not paired.
    df = synthetic_run({"b": 1.05}, drift=0.02, noise=0.005)
    assert verdicts(analyze(df))["b"] is Verdict.REGRESSION


def test_aa_comparisons_rarely_flag():
    flagged = 0
    for seed in range(200):
        df = synthetic_run({f"b{i}": 1.0 for i in range(10)}, noise=0.02, seed=seed)
        flagged += any(r.verdict in (Verdict.REGRESSION, Verdict.IMPROVEMENT)
                       for r in analyze(df, Params(n_boot=1000)).results)
    assert flagged <= 2  # family-wise alpha is 1%


def test_warmup_rounds_are_dropped():
    df = synthetic_run({"b": 1.0}, rounds=15)
    # Round 0 is a huge head-side outlier; with warmup=1 it must be ignored.
    df.loc[(df["round"] == 0) & (df["side"] == "head"), "real_time_ns"] *= 5
    result = analyze(df, Params(warmup=1)).results[0]
    assert result.n == 14
    assert result.verdict is Verdict.UNCHANGED


def test_identical_timings_give_p_of_one():
    df = synthetic_run({"b": 1.0}, noise=0.0)
    result = analyze(df).results[0]
    assert result.p_value == 1.0
    assert result.verdict is Verdict.UNCHANGED


def test_benchmarks_on_one_side_only_are_reported_not_compared():
    df = synthetic_run({"kept": 1.0, "gone": 1.0, "new": 1.0})
    df = df[~((df["benchmark"] == "gone") & (df["side"] == "head"))]
    df = df[~((df["benchmark"] == "new") & (df["side"] == "base"))]
    analysis = analyze(df)
    assert [r.benchmark for r in analysis.results] == ["kept"]
    assert analysis.only_in_base == ["gone"]
    assert analysis.only_in_head == ["new"]


def test_warns_when_too_few_rounds_to_reach_significance():
    df = synthetic_run({f"b{i}": 1.5 for i in range(14)}, rounds=6)
    analysis = analyze(df)
    assert analysis.count(Verdict.REGRESSION) == 0  # impossible with 5 usable rounds
    assert any("rounds" in w for w in analysis.warnings)


def test_min_rounds_for():
    # 2 / 2^n <= alpha / m
    assert min_rounds_for(m=1, alpha=0.05) == 6
    assert min_rounds_for(m=14, alpha=0.01) == 12


def test_holm_matches_hand_computation():
    # Sorted p: 0.01, 0.02, 0.04 -> 3*0.01, max(0.03, 2*0.02), max(0.04, 1*0.04)
    assert holm([0.04, 0.01, 0.02]) == pytest.approx([0.04, 0.03, 0.04])
    assert holm([0.9, 0.8]) == pytest.approx([1.0, 1.0])  # 2 * 0.8 capped at 1
    assert holm([]) == []


@pytest.mark.parametrize("p, low, high, expected", [
    (0.001, 1.05, 1.10, Verdict.REGRESSION),
    (0.001, 1.02, 1.10, Verdict.INCONCLUSIVE),   # significant, but could be under 3%
    (0.5, 1.05, 1.10, Verdict.INCONCLUSIVE),     # big but not significant
    (0.001, 0.90, 0.95, Verdict.IMPROVEMENT),
    (0.5, 0.98, 1.02, Verdict.UNCHANGED),
    (0.001, 0.995, 1.01, Verdict.UNCHANGED),
])
def test_classify(p, low, high, expected):
    assert classify(p, low, high, Params()) is expected
