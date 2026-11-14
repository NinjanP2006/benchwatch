"""SQLite history of benchmark results on the main branch.

Each recorded run is one `bot compare` of a commit against its parent, so a
row carries both the commit's absolute time (for trends) and the paired
change against its parent (precise, machine-independent, but per step only).
"""

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from benchwatch import parse
from benchwatch.stats import Analysis, Params, analyze

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY,
    sha          TEXT NOT NULL,
    parent_sha   TEXT NOT NULL,
    committed_at TEXT NOT NULL,
    recorded_at  TEXT NOT NULL,
    cpu_model    TEXT NOT NULL,
    platform     TEXT NOT NULL,
    rounds       INTEGER NOT NULL,
    config       TEXT NOT NULL,
    UNIQUE (sha, cpu_model)
);
CREATE TABLE IF NOT EXISTS results (
    run_id           INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    benchmark        TEXT NOT NULL,
    median_ns        REAL NOT NULL,
    ratio_vs_parent  REAL NOT NULL,
    ci_low           REAL,
    ci_high          REAL,
    p_adjusted       REAL NOT NULL,
    verdict          TEXT NOT NULL,
    n                INTEGER NOT NULL,
    PRIMARY KEY (run_id, benchmark)
);
CREATE INDEX IF NOT EXISTS results_by_benchmark ON results (benchmark);
"""


def connect(db: Path) -> sqlite3.Connection:
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


@dataclass
class Recorded:
    sha: str
    benchmarks: int
    replaced: bool


def record(db: Path, run_dir: Path, params: Params = Params(), ignore: list[str] | None = None) -> Recorded:
    """Store a `bot compare` run (head vs its parent). Re-recording the same commit
    on the same CPU model replaces the earlier row, so retried CI jobs are harmless."""
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    analysis: Analysis = analyze(parse.drop_ignored(parse.load_run(run_dir), ignore), params)
    head, base = meta["head"], meta["base"]
    cpu = meta["host"].get("cpu_model") or parse.load_context(run_dir).get("host_name", "unknown")

    with closing(connect(db)) as conn, conn:
        replaced = conn.execute("DELETE FROM runs WHERE sha = ? AND cpu_model = ?",
                                (head["sha"], cpu)).rowcount > 0
        run_id = conn.execute(
            "INSERT INTO runs (sha, parent_sha, committed_at, recorded_at, cpu_model, platform, rounds, config)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (head["sha"], base["sha"], head.get("committed_at") or meta["started_at"], meta["started_at"],
             cpu, meta["host"].get("platform", ""), meta["config"]["rounds"], json.dumps(meta["config"])),
        ).lastrowid
        conn.executemany(
            "INSERT INTO results (run_id, benchmark, median_ns, ratio_vs_parent, ci_low, ci_high,"
            " p_adjusted, verdict, n) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(run_id, r.benchmark, r.head_median_ns, r.ratio, r.ci_low, r.ci_high, r.p_adjusted,
              r.verdict.value, r.n) for r in analysis.results],
        )
    return Recorded(sha=head["sha"], benchmarks=len(analysis.results), replaced=replaced)


def load_history(db: Path, benchmark: str | None = None, cpu_model: str | None = None) -> pd.DataFrame:
    """Rows ordered by commit time. With no cpu_model, uses the model with the most runs."""
    with closing(connect(db)) as conn:
        if cpu_model is None:
            row = conn.execute("SELECT cpu_model FROM runs GROUP BY cpu_model "
                               "ORDER BY COUNT(*) DESC, MAX(recorded_at) DESC LIMIT 1").fetchone()
            if row is None:
                return pd.DataFrame(columns=HISTORY_COLUMNS)
            cpu_model = row[0]
        query = ("SELECT r.benchmark, u.sha, u.parent_sha, u.committed_at, u.cpu_model, r.median_ns,"
                 " r.ratio_vs_parent, r.ci_low, r.ci_high, r.verdict"
                 " FROM results r JOIN runs u ON u.id = r.run_id WHERE u.cpu_model = ?")
        args: list = [cpu_model]
        if benchmark is not None:
            query += " AND r.benchmark = ?"
            args.append(benchmark)
        query += " ORDER BY u.committed_at, u.recorded_at"
        return pd.read_sql_query(query, conn, params=args)


def cpu_models(db: Path) -> list[tuple[str, int]]:
    with closing(connect(db)) as conn:
        return conn.execute("SELECT cpu_model, COUNT(*) FROM runs GROUP BY cpu_model "
                            "ORDER BY COUNT(*) DESC").fetchall()


HISTORY_COLUMNS = ["benchmark", "sha", "parent_sha", "committed_at", "cpu_model", "median_ns",
                   "ratio_vs_parent", "ci_low", "ci_high", "verdict"]
