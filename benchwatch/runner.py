"""Check out two commits, build both, and run their benchmarks interleaved.

Base and head run alternately on the same machine in the same session, so
slow drift (thermal state, background load, turbo budget) affects both sides
roughly equally instead of masquerading as a regression. The order within each
round alternates (base-head, head-base, ...) so that any "second run is
faster/slower" effect cancels out too.
"""

import hashlib
import json
import platform
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SIDES = ("base", "head")


class RunnerError(RuntimeError):
    pass


@dataclass(frozen=True)
class Side:
    name: str
    rev: str
    sha: str
    cmake_args: tuple[str, ...] = ()
    committed_at: str = ""  # committer date, ISO 8601; orders the history


@dataclass(frozen=True)
class RunConfig:
    rounds: int = 15
    min_time_s: float = 0.1
    benchmark_filter: str | None = None
    source_dir: str = "target"
    bench_target: str = "bench"
    cpu: str | None = None  # pin benchmark processes with `taskset -c` (Linux only)


def cpu_model() -> str:
    """Human-readable CPU name. Absolute timings are only comparable within one model."""
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine() or "unknown"


def host_info() -> dict:
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_model": cpu_model(),
        "python": sys.version.split()[0],
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class RunMeta:
    base: Side
    head: Side
    config: RunConfig
    started_at: str = field(default_factory=utc_now)
    host: dict = field(default_factory=host_info)


# ---- git -------------------------------------------------------------------

def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RunnerError(f"git {' '.join(args)} failed:\n{proc.stderr.strip()}")
    return proc.stdout.strip()


def repo_root(path: Path) -> Path:
    return Path(git(path, "rev-parse", "--show-toplevel"))


def resolve_sha(repo: Path, rev: str) -> str:
    return git(repo, "rev-parse", "--verify", f"{rev}^{{commit}}")


def commit_time(repo: Path, sha: str) -> str:
    return git(repo, "show", "-s", "--format=%cI", sha)


def merge_base(repo: Path, a: str, b: str) -> str:
    return git(repo, "merge-base", a, b)


def ensure_worktree(repo: Path, sha: str, cache_dir: Path) -> Path:
    """Return a detached worktree checked out at `sha`, creating it if needed."""
    path = cache_dir / "worktrees" / sha[:12]
    if (path / ".git").exists():
        return path
    git(repo, "worktree", "prune")
    path.parent.mkdir(parents=True, exist_ok=True)
    git(repo, "worktree", "add", "--detach", str(path), sha)
    return path


# ---- build -----------------------------------------------------------------

def build_dir_for(side: Side, cache_dir: Path) -> Path:
    # One build per (commit, cmake args), so an injected-slowdown build of the
    # same commit doesn't overwrite the normal one.
    args_key = hashlib.sha256("\0".join(side.cmake_args).encode()).hexdigest()[:8]
    return cache_dir / "builds" / f"{side.sha[:12]}-{args_key}"


def find_executable(build_dir: Path, target: str) -> Path:
    # Single-config generators put it at the top; Visual Studio under Release/.
    for candidate in (build_dir / target, build_dir / f"{target}.exe",
                      build_dir / "Release" / f"{target}.exe", build_dir / "Release" / target):
        if candidate.is_file():
            return candidate
    raise RunnerError(f"built target '{target}' not found under {build_dir}")


def _run_logged(cmd: Sequence[str], log: Path) -> None:
    with log.open("a", encoding="utf-8") as fh:
        fh.write(f"$ {' '.join(cmd)}\n")
        fh.flush()
        proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        tail = "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-30:])
        raise RunnerError(f"command failed ({proc.returncode}): {' '.join(cmd)}\n--- last lines of {log} ---\n{tail}")


def build(side: Side, worktree: Path, cache_dir: Path, config: RunConfig) -> Path:
    """Configure (once) and build the benchmark target. Returns the executable path."""
    build_dir = build_dir_for(side, cache_dir)
    build_dir.mkdir(parents=True, exist_ok=True)
    log = build_dir / "benchwatch-build.log"

    if not (build_dir / "CMakeCache.txt").exists():
        _run_logged(["cmake", "-S", str(worktree / config.source_dir), "-B", str(build_dir),
                     "-DCMAKE_BUILD_TYPE=Release", *side.cmake_args], log)
    # Incremental; a no-op when the cached build is current.
    _run_logged(["cmake", "--build", str(build_dir), "--config", "Release",
                 "--target", config.bench_target, "--parallel"], log)
    return find_executable(build_dir, config.bench_target)


# ---- run -------------------------------------------------------------------

def schedule(rounds: int) -> list[tuple[int, str]]:
    """Interleaved run order: base,head / head,base / base,head / ..."""
    order: list[tuple[int, str]] = []
    for r in range(rounds):
        first, second = SIDES if r % 2 == 0 else SIDES[::-1]
        order += [(r, first), (r, second)]
    return order


def result_path(run_dir: Path, round_index: int, side: str) -> Path:
    return run_dir / f"round{round_index:03d}_{side}.json"


def run_benchmark(exe: Path, out: Path, config: RunConfig) -> None:
    pin = ["taskset", "-c", config.cpu] if config.cpu is not None else []
    cmd = [*pin, str(exe), f"--benchmark_out={out}", "--benchmark_out_format=json",
           "--benchmark_repetitions=1", f"--benchmark_min_time={config.min_time_s}s"]
    if config.benchmark_filter:
        cmd.append(f"--benchmark_filter={config.benchmark_filter}")
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RunnerError(f"benchmark run failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr.strip()}")


def run_comparison(
    repo: Path,
    base: Side,
    head: Side,
    config: RunConfig,
    cache_dir: Path,
    run_dir: Path,
    log: Callable[[str], None] = print,
) -> RunMeta:
    """Build both sides and run them interleaved, writing raw JSON into `run_dir`."""
    exes: dict[str, Path] = {}
    for side in (base, head):
        log(f"building {side.name} @ {side.sha[:12]}" + (f" ({' '.join(side.cmake_args)})" if side.cmake_args else ""))
        worktree = ensure_worktree(repo, side.sha, cache_dir)
        exes[side.name] = build(side, worktree, cache_dir, config)

    run_dir.mkdir(parents=True, exist_ok=False)
    meta = RunMeta(base=base, head=head, config=config)
    (run_dir / "meta.json").write_text(json.dumps(asdict(meta), indent=2), encoding="utf-8")

    plan = schedule(config.rounds)
    for i, (round_index, side) in enumerate(plan, start=1):
        log(f"[{i}/{len(plan)}] round {round_index + 1}/{config.rounds} {side}")
        run_benchmark(exes[side], result_path(run_dir, round_index, side), config)
    return meta


# ---- validation pools --------------------------------------------------------

REF_SUFFIX = "-ref"


def paired_schedule(rounds: int, labels: Sequence[str]) -> list[tuple[int, str]]:
    """Every label runs back to back with its own reference run, exactly like base
    and head in `compare`, so the pool has the same pairing noise as a real PR run.
    Pairs alternate order by round (ref-first, then variant-first), and the order of
    the pairs rotates so no variant is always first or last in a round."""
    order: list[tuple[int, str]] = []
    k = len(labels)
    for r in range(rounds):
        for i in range(k):
            label = labels[(r + i) % k]
            pair = [label + REF_SUFFIX, label]
            order += [(r, side) for side in (pair if r % 2 == 0 else pair[::-1])]
    return order


def collect_pool(
    repo: Path,
    sha: str,
    reference_args: tuple[str, ...],
    variants: dict[str, tuple[str, ...]],
    config: RunConfig,
    cache_dir: Path,
    pool_dir: Path,
    extra_meta: dict | None = None,
    log: Callable[[str], None] = print,
) -> None:
    """Build one commit as a reference plus one build per variant (label -> extra
    CMake args), then run each variant paired with an adjacent reference run.
    A variant whose args equal the reference's reuses its executable, which is
    how A/A pairs are produced."""
    worktree = ensure_worktree(repo, sha, cache_dir)
    built: dict[tuple[str, ...], Path] = {}

    def exe_for(args: tuple[str, ...]) -> Path:
        if args not in built:
            log(f"building {sha[:12]} {' '.join(args) or '(no extra args)'}")
            built[args] = build(Side("pool", sha, sha, args), worktree, cache_dir, config)
        return built[args]

    reference = exe_for(reference_args)
    exes = {label: exe_for(args) for label, args in variants.items()}
    exes |= {label + REF_SUFFIX: reference for label in variants}

    pool_dir.mkdir(parents=True, exist_ok=False)
    meta = {"sha": sha, "reference": list(reference_args),
            "variants": {k: list(v) for k, v in variants.items()}, "config": asdict(config),
            "started_at": utc_now(), "host": host_info(), **(extra_meta or {})}
    (pool_dir / "pool-meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    plan = paired_schedule(config.rounds, list(variants))
    per_round = 2 * len(variants)
    for i, (round_index, side) in enumerate(plan):
        if i % per_round == 0:
            log(f"round {round_index + 1}/{config.rounds}")
        run_benchmark(exes[side], result_path(pool_dir, round_index, side), config)
