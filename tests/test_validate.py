import json

import numpy as np
import pandas as pd
import pytest

from benchwatch.runner import REF_SUFFIX, paired_schedule
from benchwatch.validate import (AA, POOL_CSV, POOL_META, Pool, headline, load_pool, measured_effects,
                                 per_benchmark, simulate, summarize, variant_plan)

EFFECTS = {AA: 0.0, "inject1": 1.0, "inject5": 5.0, "inject10": 10.0}


def synthetic_pool(rounds=40, benchmarks=6, noise=0.01, seed=3) -> Pool:
    rng = np.random.default_rng(seed)
    base_level = rng.uniform(1e3, 1e6, size=(benchmarks, 1))

    def draw(effect_pct):
        return base_level * (1 + effect_pct / 100) * np.exp(rng.normal(0, noise, size=(benchmarks, rounds)))

    times = {}
    for label, effect in EFFECTS.items():
        times[label + REF_SUFFIX] = draw(0.0)
        times[label] = draw(effect)
    return Pool(benchmarks=[f"BM_{i}" for i in range(benchmarks)], times=times, effects=EFFECTS,
                meta={"sha": "f" * 40})


@pytest.fixture(scope="module")
def simulated():
    pool = synthetic_pool()
    sim = simulate(pool, rounds_list=[10, 20], thresholds=[0.03], trials=60, n_boot=500)
    return pool, sim, summarize(sim, pool)


def row(summary, variant, rounds, threshold=0.03):
    sel = summary[(summary["variant"] == variant) & (summary["rounds"] == rounds) & (summary["threshold"] == threshold)]
    assert len(sel) == 1
    return sel.iloc[0]


def test_large_injections_are_detected(simulated):
    _, _, summary = simulated
    assert row(summary, "inject10", 20)["regression_rate"] == 1.0
    assert row(summary, "inject5", 20)["regression_rate"] > 0.9


def test_power_grows_with_rounds(simulated):
    _, _, summary = simulated
    assert row(summary, "inject5", 20)["regression_rate"] >= row(summary, "inject5", 10)["regression_rate"]


def test_sub_threshold_slowdown_is_not_flagged(simulated):
    _, _, summary = simulated
    assert row(summary, "inject1", 20)["regression_rate"] == 0.0


def test_aa_false_alarm_rate_is_low(simulated):
    _, _, summary = simulated
    aa = row(summary, AA, 20)
    assert aa["any_flag_rate"] <= 0.05
    assert aa["regression_rate"] + aa["improvement_rate"] <= 0.01


def test_rates_sum_to_one(simulated):
    _, _, summary = simulated
    total = summary[["regression_rate", "improvement_rate", "unchanged_rate", "inconclusive_rate"]].sum(axis=1)
    assert np.allclose(total, 1.0)


def test_measured_effects_recover_injection(simulated):
    pool, _, _ = simulated
    measured = measured_effects(pool)
    assert measured["inject5"] == pytest.approx(5.0, abs=0.5)
    assert measured[AA] == pytest.approx(0.0, abs=0.5)


def test_per_benchmark_has_one_row_per_benchmark(simulated):
    pool, sim, _ = simulated
    pb = per_benchmark(sim)
    assert len(pb) == len(EFFECTS) * 2 * len(pool.benchmarks)


def test_headline_mentions_rates(simulated):
    _, _, summary = simulated
    text = headline(summary, rounds=20, threshold=0.03)
    assert "5% slowdown" in text and "of runs" in text


def test_simulate_rejects_more_rounds_than_pool():
    with pytest.raises(ValueError):
        simulate(synthetic_pool(rounds=8), rounds_list=[10], thresholds=[0.03], trials=1)


def test_load_pool_drops_warmup_and_incomplete_rounds(tmp_path):
    rows = []
    for r in range(5):
        for label in (AA + REF_SUFFIX, AA):
            if (r, label) == (3, AA):
                continue  # a failed run: round 3 must be dropped entirely
            rows.append(dict(benchmark="BM_x", side=label, round=r, real_time_ns=100.0 + r,
                             cpu_time_ns=100.0, iterations=1))
    pd.DataFrame(rows).to_csv(tmp_path / POOL_CSV, index=False)
    (tmp_path / POOL_META).write_text(json.dumps({"sha": "a" * 40, "effects": {AA: 0.0}}))

    pool = load_pool(tmp_path, warmup=1)
    assert pool.rounds == 3  # rounds 1, 2, 4
    assert pool.pair(AA)[0].tolist() == [[101.0, 102.0, 104.0]]


def test_variant_plan():
    variants, effects = variant_plan([2.5, 10], "INJECT")
    assert variants == {AA: (), "inject2p5": ("-DINJECT=2.5",), "inject10": ("-DINJECT=10",)}
    assert effects == {AA: 0.0, "inject2p5": 2.5, "inject10": 10.0}


def test_paired_schedule_keeps_each_variant_next_to_its_reference():
    plan = paired_schedule(2, ["a", "b"])
    assert [side for _, side in plan] == ["a-ref", "a", "b-ref", "b",   # round 0: ref first
                                          "b", "b-ref", "a", "a-ref"]   # round 1: rotated, variant first
    for r in range(4):
        sides = [s for rr, s in paired_schedule(4, ["a", "b", "c"]) if rr == r]
        for i in range(0, len(sides), 2):
            assert sides[i].removesuffix(REF_SUFFIX) == sides[i + 1].removesuffix(REF_SUFFIX)
