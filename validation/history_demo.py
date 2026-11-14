"""Build a demo history with a slow creep that no single PR would flag.

Clones this repo into a scratch directory and makes a chain of commits. Five
consecutive commits each raise the injected slowdown by 1% (below the 3%
per-PR threshold); the rest change nothing that affects timing. Every commit
is then compared with its parent and recorded, exactly as the `history`
workflow does on main, so `bot history` can show whether the creep is found.

    uv run python validation/history_demo.py
    uv run bot history BM_Sort/65536 --db validation/history-demo/benchwatch-history.db
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CMAKE_DEFAULT = re.compile(r'set\(PERFKIT_INJECT_SLOWDOWN_PCT "[^"]*"')


def run(*cmd: str, cwd: Path | None = None) -> str:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"failed: {' '.join(cmd)}\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
    return proc.stdout.strip()


def git(repo: Path, *args: str) -> str:
    return run("git", "-C", str(repo), "-c", "user.name=demo", "-c", "user.email=demo@example.invalid", *args)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--commits", type=int, default=24)
    ap.add_argument("--creep-start", type=int, default=10, help="index of the first slowing commit")
    ap.add_argument("--creep-steps", type=int, default=5)
    ap.add_argument("--step-pct", type=float, default=1.0)
    ap.add_argument("--rounds", type=int, default=11)
    ap.add_argument("--filter", default="BM_Sort/65536|BM_ParseCsvInts/65536|BM_FlatMapLookup/1024")
    ap.add_argument("--workdir", type=Path, default=ROOT / ".benchwatch" / "demo")
    ap.add_argument("--db", type=Path, default=ROOT / "validation" / "history-demo" / "benchwatch-history.db")
    args = ap.parse_args()

    if args.workdir.exists():
        shutil.rmtree(args.workdir)
    run("git", "clone", "-q", str(ROOT), str(args.workdir))
    repo = args.workdir
    args.db.unlink(missing_ok=True)

    cmakelists = repo / "target" / "CMakeLists.txt"
    log = repo / "demo-log.txt"
    for i in range(args.commits):
        steps_done = min(max(i - args.creep_start + 1, 0), args.creep_steps)
        pct = steps_done * args.step_pct
        text = CMAKE_DEFAULT.sub(f'set(PERFKIT_INJECT_SLOWDOWN_PCT "{pct:g}"', cmakelists.read_text())
        cmakelists.write_text(text)
        with log.open("a") as fh:
            fh.write(f"commit {i}: injected slowdown {pct:g}%\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", f"Demo commit {i} ({pct:g}% injected)")

    shas = git(repo, "rev-list", "--reverse", f"HEAD~{args.commits}..HEAD").split()
    bot = [sys.executable, "-m", "benchwatch"]
    deps = (repo / "_deps").as_posix()  # share fetched deps across builds to save time
    for i, sha in enumerate(shas):
        print(f"[{i + 1}/{len(shas)}] {sha[:7]}", flush=True)
        results = repo / "results" / f"{i:03d}"
        run(*bot, "compare", "--repo", str(repo), "--base", f"{sha}^1", "--head", sha,
            "--rounds", str(args.rounds), "--filter", args.filter, f"--cmake-arg=-DFETCHCONTENT_BASE_DIR={deps}",
            "--results-dir", str(results), "--no-fail-on-regression")
        run_dir = next(results.iterdir())
        print("   ", run(*bot, "record", str(run_dir), "--db", str(args.db)), flush=True)


if __name__ == "__main__":
    main()
