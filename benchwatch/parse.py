"""Turn a run directory of Google Benchmark JSON files into one tidy table."""

import json
import re
from pathlib import Path

import pandas as pd

COLUMNS = ["benchmark", "side", "round", "real_time_ns", "cpu_time_ns", "iterations"]

_TIME_UNIT_NS = {"ns": 1.0, "us": 1e3, "ms": 1e6, "s": 1e9}
# Side is "base"/"head" for comparisons, or a variant label for validation pools.
_FILENAME = re.compile(r"round(\d+)_([A-Za-z0-9-]+)\.json")


def parse_benchmark_json(data: dict, side: str, round_index: int) -> list[dict]:
    rows = []
    for b in data.get("benchmarks", []):
        # Only raw measurements; aggregates (mean/median/cv) are computed by us.
        if b.get("run_type", "iteration") != "iteration" or b.get("error_occurred"):
            continue
        scale = _TIME_UNIT_NS[b.get("time_unit", "ns")]
        rows.append({
            "benchmark": b.get("run_name", b["name"]),
            "side": side,
            "round": round_index,
            "real_time_ns": b["real_time"] * scale,
            "cpu_time_ns": b["cpu_time"] * scale,
            "iterations": b["iterations"],
        })
    return rows


def load_run(run_dir: Path) -> pd.DataFrame:
    rows: list[dict] = []
    for path in sorted(run_dir.glob("round*_*.json")):
        m = _FILENAME.fullmatch(path.name)
        if not m:
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        rows += parse_benchmark_json(data, side=m.group(2), round_index=int(m.group(1)))
    if not rows:
        raise FileNotFoundError(f"no benchmark results found in {run_dir}")
    return pd.DataFrame(rows, columns=COLUMNS)


def drop_ignored(df: pd.DataFrame, patterns: list[str] | None) -> pd.DataFrame:
    """Remove benchmarks whose name matches any regex (re.search)."""
    if not patterns:
        return df
    regex = re.compile("|".join(f"(?:{p})" for p in patterns))
    return df[~df["benchmark"].map(lambda name: bool(regex.search(name)))]


def load_context(run_dir: Path) -> dict:
    """Google Benchmark's machine context (CPU, caches, load) from the first result file."""
    first = next(iter(sorted(run_dir.glob("round*_*.json"))), None)
    return json.loads(first.read_text(encoding="utf-8")).get("context", {}) if first else {}
