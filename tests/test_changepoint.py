import numpy as np
import pytest

from benchwatch.changepoint import find_changepoints, segment_levels


def noisy(levels, noise=0.005, seed=0):
    rng = np.random.default_rng(seed)
    x = np.asarray(levels, dtype=float)
    return x * np.exp(rng.normal(0, noise, size=len(x)))


def test_flat_series_has_no_changepoints():
    for seed in range(20):
        assert find_changepoints(noisy([100.0] * 30, noise=0.01, seed=seed)) == []


def test_single_step_is_found_at_the_right_commit():
    x = noisy([100.0] * 12 + [106.0] * 12)
    [cp] = find_changepoints(x)
    assert cp.index == 12
    assert cp.shift == pytest.approx(0.06, abs=0.01)


def test_slow_creep_of_sub_threshold_steps_is_caught():
    # Five +1% commits: each below the 3% per-PR threshold, ~5% in total.
    levels = [100.0] * 10 + [100.0 * 1.01 ** k for k in range(1, 6)] + [100.0 * 1.01 ** 5] * 10
    x = noisy(levels, noise=0.003)
    assert np.all(np.abs(np.diff(levels)) / np.array(levels[:-1]) < 0.03)
    cps = find_changepoints(x)
    assert len(cps) == 1
    assert 10 <= cps[0].index <= 15
    assert cps[0].shift > 0.03


def test_shift_below_threshold_is_ignored():
    x = noisy([100.0] * 12 + [102.0] * 12, noise=0.001)
    assert find_changepoints(x, threshold=0.03) == []
    assert len(find_changepoints(x, threshold=0.01)) == 1


def test_regression_then_fix_is_found_as_two_steps():
    x = noisy([100.0] * 10 + [110.0] * 10 + [100.0] * 10)
    assert [c.index for c in find_changepoints(x)] == [10, 20]


def test_short_series_and_changes_near_the_ends():
    assert find_changepoints([100.0, 200.0, 200.0]) == []
    x = noisy([100.0] * 3 + [120.0] * 10)
    assert find_changepoints(x, window=5) == []  # change closer to the start than the window


def test_segment_levels():
    x = [1.0, 1.0, 1.0, 1.0, 1.0, 2.0, 2.0, 2.0, 2.0, 2.0]
    cps = find_changepoints(np.array(x) * np.linspace(1, 1.001, 10), window=5, threshold=0.1)
    assert segment_levels(x, cps).tolist() == x
