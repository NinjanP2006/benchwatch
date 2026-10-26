from pathlib import Path

import pytest

from benchwatch.runner import RunnerError, Side, build_dir_for, find_executable, schedule


def test_schedule_alternates_order_each_round():
    assert schedule(3) == [(0, "base"), (0, "head"), (1, "head"), (1, "base"), (2, "base"), (2, "head")]


def test_schedule_runs_each_side_once_per_round():
    plan = schedule(10)
    for side in ("base", "head"):
        assert sorted(r for r, s in plan if s == side) == list(range(10))


def test_build_dir_differs_by_cmake_args():
    cache = Path("/cache")
    plain = Side("head", "HEAD", "a" * 40)
    injected = Side("head", "HEAD", "a" * 40, ("-DPERFKIT_INJECT_SLOWDOWN_PCT=5",))
    assert build_dir_for(plain, cache) != build_dir_for(injected, cache)
    assert build_dir_for(plain, cache) == build_dir_for(Side("base", "main", "a" * 40), cache)


@pytest.mark.parametrize("relative", ["bench", "bench.exe", "Release/bench.exe"])
def test_find_executable_handles_generator_layouts(tmp_path, relative):
    exe = tmp_path / relative
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("")
    assert find_executable(tmp_path, "bench") == exe


def test_find_executable_missing_raises(tmp_path):
    with pytest.raises(RunnerError):
        find_executable(tmp_path, "bench")
