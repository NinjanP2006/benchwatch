"""Find step changes in a benchmark's history across commits.

The per-PR check compares one commit with its parent and ignores changes
below the threshold, so a 1% slowdown merged five times in a row is never
flagged. Looking at the whole series catches that creep.

Method (rolling window): at every commit k, compare the `window` commits
before it with the `window` commits from k on, using a Mann-Whitney U test.
Take the strongest split, accept it if

* the median shift between the two windows is larger than `threshold`, and
* its p-value, Bonferroni-corrected for the number of positions scanned, is
  below `alpha` (scanning for the best split and then testing it would
  otherwise make noise look significant),

then exclude commits within `window` of it and repeat.

Binary segmentation over the whole series was tried first. It misses a
regression that is later fixed (a bump): every single split of the whole
series mixes the two low segments, so none looks significant. Local windows
see the rise and the fall separately. The cost is that a change closer than
`window` commits to either end of the history cannot be detected yet.
"""

import warnings
from dataclasses import dataclass

import numpy as np
from scipy import stats as sps


@dataclass(frozen=True)
class Changepoint:
    index: int          # first point of the new level
    before_median: float
    after_median: float
    p_value: float      # Bonferroni-corrected

    @property
    def shift(self) -> float:
        return self.after_median / self.before_median - 1


def _window_p(before: np.ndarray, after: np.ndarray) -> float:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return float(sps.mannwhitneyu(before, after, alternative="two-sided", method="auto").pvalue)


def find_changepoints(values, window: int = 10, alpha: float = 0.01,
                      threshold: float = 0.03) -> list[Changepoint]:
    x = np.asarray(values, dtype=float)
    positions = list(range(window, len(x) - window + 1))
    if not positions:
        return []

    candidates: list[Changepoint] = []
    for k in positions:
        before, after = x[k - window:k], x[k:k + window]
        shift = np.median(after) / np.median(before) - 1
        if abs(shift) <= threshold:
            continue
        p = min(1.0, _window_p(before, after) * len(positions))
        if p < alpha:
            candidates.append(Changepoint(k, float(np.median(before)), float(np.median(after)), p))

    # Strongest first; then drop candidates too close to an accepted one.
    found: list[Changepoint] = []
    for c in sorted(candidates, key=lambda c: (c.p_value, -abs(c.shift))):
        if all(abs(c.index - f.index) >= window for f in found):
            found.append(c)
    return sorted(found, key=lambda c: c.index)


def segment_levels(values, changepoints: list[Changepoint]) -> np.ndarray:
    """Median of each segment, broadcast back to every point (for plotting)."""
    x = np.asarray(values, dtype=float)
    bounds = [0, *(c.index for c in changepoints), len(x)]
    levels = np.empty_like(x)
    for a, b in zip(bounds, bounds[1:]):
        levels[a:b] = np.median(x[a:b])
    return levels
