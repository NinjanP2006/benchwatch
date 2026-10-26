import json

import pytest

from benchwatch.parse import load_context, load_run, parse_benchmark_json


def gb_output(entries):
    return {"context": {"num_cpus": 8, "library_build_type": "release"}, "benchmarks": entries}


ITERATION = {"name": "BM_Sort/4096", "run_name": "BM_Sort/4096", "run_type": "iteration",
             "iterations": 5000, "real_time": 135.5, "cpu_time": 134.0, "time_unit": "us"}


def test_normalises_time_units_to_ns():
    rows = parse_benchmark_json(gb_output([
        ITERATION,
        {**ITERATION, "name": "BM_X", "run_name": "BM_X", "real_time": 2.0, "cpu_time": 2.0, "time_unit": "ms"},
        {**ITERATION, "name": "BM_Y", "run_name": "BM_Y", "real_time": 7.0, "cpu_time": 7.0, "time_unit": "ns"},
    ]), side="base", round_index=0)
    assert [r["real_time_ns"] for r in rows] == pytest.approx([135_500, 2_000_000, 7])


def test_skips_aggregates_and_errors():
    rows = parse_benchmark_json(gb_output([
        ITERATION,
        {**ITERATION, "name": "BM_Sort/4096_median", "run_type": "aggregate", "aggregate_name": "median"},
        {**ITERATION, "name": "BM_Bad", "run_name": "BM_Bad", "error_occurred": True},
    ]), side="head", round_index=3)
    assert len(rows) == 1
    assert rows[0] == {"benchmark": "BM_Sort/4096", "side": "head", "round": 3,
                       "real_time_ns": pytest.approx(135_500), "cpu_time_ns": pytest.approx(134_000),
                       "iterations": 5000}


def test_load_run_reads_round_and_side_from_filenames(tmp_path):
    for r in range(2):
        for side in ("base", "head"):
            (tmp_path / f"round{r:03d}_{side}.json").write_text(json.dumps(gb_output([ITERATION])))
    (tmp_path / "meta.json").write_text("{}")  # must be ignored

    df = load_run(tmp_path)
    assert len(df) == 4
    assert sorted(set(zip(df["round"], df["side"]))) == [(0, "base"), (0, "head"), (1, "base"), (1, "head")]
    assert load_context(tmp_path)["num_cpus"] == 8


def test_load_run_on_empty_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_run(tmp_path)
