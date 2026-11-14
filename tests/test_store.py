import json

import numpy as np

from benchwatch import store


def fake_run(path, head_sha, parent_sha, committed_at, head_time, cpu="CPU A", rounds=15, seed=0):
    """A run directory shaped like `bot compare` output, with two benchmarks."""
    rng = np.random.default_rng(seed)
    path.mkdir(parents=True)
    (path / "meta.json").write_text(json.dumps({
        "base": {"sha": parent_sha, "rev": "parent"},
        "head": {"sha": head_sha, "rev": "HEAD", "committed_at": committed_at},
        "config": {"rounds": rounds},
        "started_at": "2026-11-12T00:00:00+00:00",
        "host": {"platform": "Linux", "cpu_model": cpu},
    }))
    for r in range(rounds):
        for side, scale in (("base", 1.0), ("head", head_time / 100.0)):
            benches = [{"name": n, "run_name": n, "run_type": "iteration", "iterations": 10,
                        "real_time": 100.0 * scale * mult * np.exp(rng.normal(0, 0.002)),
                        "cpu_time": 1.0, "time_unit": "us"} for n, mult in (("BM_A", 1.0), ("BM_B", 2.0))]
            (path / f"round{r:03d}_{side}.json").write_text(json.dumps({"benchmarks": benches}))
    return path


def test_record_and_load_in_commit_order(tmp_path):
    db = tmp_path / "h.db"
    # Recorded out of order; history must follow commit time.
    store.record(db, fake_run(tmp_path / "r2", "b" * 40, "a" * 40, "2026-01-02T00:00:00+00:00", 110.0))
    store.record(db, fake_run(tmp_path / "r1", "a" * 40, "0" * 40, "2026-01-01T00:00:00+00:00", 100.0))

    df = store.load_history(db, "BM_A")
    assert df["sha"].str[:1].tolist() == ["a", "b"]
    assert df["median_ns"].iloc[1] / df["median_ns"].iloc[0] == np.float64(df["median_ns"].iloc[1] / df["median_ns"].iloc[0])
    assert abs(df["ratio_vs_parent"].iloc[1] - 1.10) < 0.01
    assert df["verdict"].iloc[1] == "regression"
    assert set(store.load_history(db)["benchmark"]) == {"BM_A", "BM_B"}


def test_rerecording_a_commit_replaces_it(tmp_path):
    db = tmp_path / "h.db"
    first = store.record(db, fake_run(tmp_path / "r1", "a" * 40, "0" * 40, "2026-01-01T00:00:00+00:00", 100.0))
    again = store.record(db, fake_run(tmp_path / "r2", "a" * 40, "0" * 40, "2026-01-01T00:00:00+00:00", 100.0, seed=1))
    assert not first.replaced and again.replaced
    assert len(store.load_history(db, "BM_A")) == 1


def test_series_are_kept_per_cpu_model(tmp_path):
    db = tmp_path / "h.db"
    for i in range(3):
        store.record(db, fake_run(tmp_path / f"a{i}", f"{i}" * 40, "f" * 40, f"2026-01-0{i + 1}T00:00:00+00:00",
                                  100.0, cpu="CPU A"))
    store.record(db, fake_run(tmp_path / "b0", "9" * 40, "f" * 40, "2026-01-05T00:00:00+00:00", 100.0, cpu="CPU B"))

    assert store.cpu_models(db) == [("CPU A", 3), ("CPU B", 1)]
    assert set(store.load_history(db, "BM_A")["cpu_model"]) == {"CPU A"}  # most-recorded model by default
    assert len(store.load_history(db, "BM_A", cpu_model="CPU B")) == 1


def test_empty_db_gives_empty_history(tmp_path):
    assert store.load_history(tmp_path / "empty.db").empty
