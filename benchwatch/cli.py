"""Command-line entry point: `bot compare`, `bot analyze`, `bot clean`."""

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

from benchwatch import changepoint, github, parse, report, runner, store, validate
from benchwatch.stats import Params, analyze

app = typer.Typer(no_args_is_help=True, add_completion=False,
                  help="Detect statistically meaningful benchmark regressions between two commits.")
console = Console()

CACHE_DIRNAME = ".benchwatch"

# Shared statistics options, so `compare` and `analyze` stay in sync.
AlphaOpt = Annotated[float, typer.Option(help="Family-wise significance level across all benchmarks.")]
ThresholdOpt = Annotated[float, typer.Option(help="Smallest change that counts, as a fraction (0.03 = 3%).")]
WarmupOpt = Annotated[int, typer.Option(help="Leading rounds to discard.")]
OutOpt = Annotated[Optional[Path], typer.Option("--out", help="Also write the analysis as JSON to this file.")]
MarkdownOpt = Annotated[Optional[Path], typer.Option("--markdown", help="Also write a PR-comment Markdown report.")]
FailOpt = Annotated[bool, typer.Option(help="Exit with status 1 if any regression is found.")]

# Shared run options for `compare` and `collect`.
MinTimeOpt = Annotated[float, typer.Option(help="Google Benchmark min time per benchmark per run, seconds.")]
FilterOpt = Annotated[Optional[str], typer.Option("--filter", help="Regex passed to --benchmark_filter.")]
CmakeArgOpt = Annotated[Optional[list[str]], typer.Option(help="Extra CMake arg for every build (repeatable), e.g. a compiler launcher.")]
CpuOpt = Annotated[Optional[str], typer.Option(help="Pin benchmark runs to these CPUs with taskset (Linux), e.g. '2' or '2,3'.")]
RepoPathOpt = Annotated[Path, typer.Option(help="Repository to benchmark.")]
SourceDirOpt = Annotated[str, typer.Option(help="CMake source directory, relative to the repo root.")]
BenchTargetOpt = Annotated[str, typer.Option(help="CMake target of the benchmark executable.")]


def _float_list(text: str) -> list[float]:
    return [float(x) for x in text.split(",") if x.strip()]


def _int_list(text: str) -> list[int]:
    return [int(x) for x in text.split(",") if x.strip()]


def _title(meta: dict) -> str:
    return (f"base {meta['base']['rev']} ({meta['base']['sha'][:7]})  vs  "
            f"head {meta['head']['rev']} ({meta['head']['sha'][:7]})")


def _analyze_and_report(run_dir: Path, params: Params, out: Path | None, markdown: Path | None,
                        fail_on_regression: bool) -> None:
    meta_path = run_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else None

    analysis = analyze(parse.load_run(run_dir), params)
    report.render(analysis, console, title=_title(meta) if meta else str(run_dir))
    for path, text in ((out, lambda: json.dumps(report.to_dict(analysis), indent=2)),
                       (markdown, lambda: report.to_markdown(analysis, meta, parse.load_context(run_dir)))):
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text(), encoding="utf-8")
            console.print(f"wrote {path}")
    if fail_on_regression and analysis.regressions:
        raise typer.Exit(code=1)


@app.command()
def compare(
    base: Annotated[Optional[str], typer.Option(help="Base revision. Default: merge-base of --main and --head.")] = None,
    head: Annotated[str, typer.Option(help="Head revision.")] = "HEAD",
    main: Annotated[str, typer.Option(help="Branch used to compute the default base.")] = "main",
    rounds: Annotated[int, typer.Option(min=2, help="Interleaved rounds (each runs base and head once).")] = 15,
    min_time: MinTimeOpt = 0.1,
    benchmark_filter: FilterOpt = None,
    cmake_arg: CmakeArgOpt = None,
    base_cmake_arg: Annotated[Optional[list[str]], typer.Option(help="Extra CMake arg for base (repeatable). Use the --opt=value form.")] = None,
    head_cmake_arg: Annotated[Optional[list[str]], typer.Option(help="Extra CMake arg for head (repeatable). Use the --opt=value form.")] = None,
    cpu: CpuOpt = None,
    repo: RepoPathOpt = Path("."),
    source_dir: SourceDirOpt = "target",
    bench_target: BenchTargetOpt = "bench",
    results_dir: Annotated[Optional[Path], typer.Option(help="Where raw run data goes. Default: <repo>/results.")] = None,
    alpha: AlphaOpt = 0.01,
    threshold: ThresholdOpt = 0.03,
    warmup: WarmupOpt = 1,
    out: OutOpt = None,
    markdown: MarkdownOpt = None,
    fail_on_regression: FailOpt = True,
) -> None:
    """Build two revisions and compare their benchmarks with interleaved runs."""
    if warmup >= rounds:
        raise typer.BadParameter("--warmup must be smaller than --rounds")
    try:
        root = runner.repo_root(repo)
        head_sha = runner.resolve_sha(root, head)
        if base is None:
            base, base_sha = f"merge-base({main}, {head})", runner.merge_base(root, main, head_sha)
        else:
            base_sha = runner.resolve_sha(root, base)

        shared = tuple(cmake_arg or ())
        base_side = runner.Side("base", base, base_sha, shared + tuple(base_cmake_arg or ()),
                                runner.commit_time(root, base_sha))
        head_side = runner.Side("head", head, head_sha, shared + tuple(head_cmake_arg or ()),
                                runner.commit_time(root, head_sha))
        if base_side.sha == head_side.sha and base_side.cmake_args == head_side.cmake_args:
            console.print("[yellow]base and head are identical: this is an A/A comparison[/]")

        config = runner.RunConfig(rounds=rounds, min_time_s=min_time, benchmark_filter=benchmark_filter,
                                  source_dir=source_dir, bench_target=bench_target, cpu=cpu)
        run_id = f"{datetime.now():%Y%m%d-%H%M%S}-{base_sha[:7]}-{head_sha[:7]}"
        run_dir = (results_dir or root / "results") / run_id

        runner.run_comparison(root, base_side, head_side, config, root / CACHE_DIRNAME, run_dir,
                              log=lambda msg: console.print(f"[dim]{msg}[/]"))
    except runner.RunnerError as e:
        console.print(f"[bold red]error:[/] {e}")
        raise typer.Exit(code=2)

    console.print(f"raw results: {run_dir}")
    _analyze_and_report(run_dir, Params(alpha=alpha, threshold=threshold, warmup=warmup), out, markdown,
                        fail_on_regression)


@app.command(name="analyze")
def analyze_cmd(
    run_dir: Annotated[Path, typer.Argument(help="A run directory written by `bot compare`.", exists=True, file_okay=False)],
    alpha: AlphaOpt = 0.01,
    threshold: ThresholdOpt = 0.03,
    warmup: WarmupOpt = 1,
    out: OutOpt = None,
    markdown: MarkdownOpt = None,
    fail_on_regression: FailOpt = True,
) -> None:
    """Re-run the statistics on saved results, e.g. to try other thresholds."""
    _analyze_and_report(run_dir, Params(alpha=alpha, threshold=threshold, warmup=warmup), out, markdown,
                        fail_on_regression)


@app.command()
def collect(
    out: Annotated[Path, typer.Option(help="New directory for the pool.")],
    rev: Annotated[str, typer.Option(help="Revision to build every variant from.")] = "HEAD",
    rounds: Annotated[int, typer.Option(min=2, help="Rounds; each runs every variant once, next to its own reference run.")] = 40,
    inject: Annotated[str, typer.Option(help="Comma-separated slowdowns to inject, in percent.")] = "1,3,5,10",
    inject_var: Annotated[str, typer.Option(help="CMake variable that sets the injected slowdown.")] = "PERFKIT_INJECT_SLOWDOWN_PCT",
    min_time: MinTimeOpt = 0.1,
    benchmark_filter: FilterOpt = None,
    cmake_arg: CmakeArgOpt = None,
    cpu: CpuOpt = None,
    repo: RepoPathOpt = Path("."),
    source_dir: SourceDirOpt = "target",
    bench_target: BenchTargetOpt = "bench",
) -> None:
    """Collect a validation pool: one commit at several injected slowdowns, run round-robin."""
    try:
        root = runner.repo_root(repo)
        sha = runner.resolve_sha(root, rev)
        variants, effects = validate.variant_plan(_float_list(inject), inject_var)
        shared = tuple(cmake_arg or ())
        variants = {label: shared + args for label, args in variants.items()}
        config = runner.RunConfig(rounds=rounds, min_time_s=min_time, benchmark_filter=benchmark_filter,
                                  source_dir=source_dir, bench_target=bench_target, cpu=cpu)
        runner.collect_pool(root, sha, shared, variants, config, root / CACHE_DIRNAME, out,
                            extra_meta={"effects": effects}, log=lambda msg: console.print(f"[dim]{msg}[/]"))
    except runner.RunnerError as e:
        console.print(f"[bold red]error:[/] {e}")
        raise typer.Exit(code=2)
    parse.load_run(out).to_csv(out / validate.POOL_CSV, index=False)
    console.print(f"pool written to {out} ({rounds} rounds x {len(variants)} variant pairs)")


@app.command(name="simulate")
def simulate_cmd(
    pool_dir: Annotated[Path, typer.Argument(help="A pool written by `bot collect`.", exists=True, file_okay=False)],
    rounds: Annotated[str, typer.Option(help="Comma-separated round counts to evaluate.")] = "5,10,15,20,30",
    threshold: Annotated[str, typer.Option(help="Comma-separated thresholds to evaluate.")] = "0.02,0.03,0.05",
    trials: Annotated[int, typer.Option(help="Virtual runs per round count.")] = 300,
    alpha: AlphaOpt = 0.01,
    warmup: WarmupOpt = 1,
    seed: Annotated[int, typer.Option(help="Resampling seed.")] = 0,
    out_dir: Annotated[Optional[Path], typer.Option(help="Write summary.csv, per_benchmark.csv and REPORT.md here.")] = None,
    headline_rounds: Annotated[int, typer.Option(help="Round count used for the headline sentence.")] = 15,
    plot: Annotated[bool, typer.Option(help="Also render charts into --out-dir (needs the 'plot' extra).")] = False,
) -> None:
    """Estimate detection and false-positive rates by resampling a pool."""
    pool = validate.load_pool(pool_dir, warmup=warmup)
    thresholds = _float_list(threshold)
    console.print(f"pool: {len(pool.benchmarks)} benchmarks x {pool.rounds} usable rounds; "
                  f"variants {', '.join(pool.effects)}")
    try:
        sim = validate.simulate(pool, _int_list(rounds), thresholds, trials, alpha=alpha, seed=seed)
    except ValueError as e:
        raise typer.BadParameter(str(e))
    summary = validate.summarize(sim, pool)

    for t in thresholds:
        report.render_validation(summary[summary["threshold"] == t], console, t)
    headline_threshold = 0.03 if 0.03 in thresholds else thresholds[0]
    line = validate.headline(summary, headline_rounds, headline_threshold)
    console.print(f"\n[bold]{line}[/]")

    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        summary.to_csv(out_dir / "summary.csv", index=False)
        validate.per_benchmark(sim).to_csv(out_dir / "per_benchmark.csv", index=False)
        (out_dir / "REPORT.md").write_text(
            report.validation_markdown(summary, pool, line, trials, alpha, warmup), encoding="utf-8")
        if plot:
            from benchwatch import plot as plotting
            for theme in ("light", "dark"):
                plotting.render(summary, headline_threshold, out_dir / f"validation-{theme}.png", theme)
        console.print(f"wrote {out_dir}")


DbOpt = Annotated[Path, typer.Option("--db", help="SQLite history database.")]


@app.command(name="record")
def record_cmd(
    run_dir: Annotated[Path, typer.Argument(help="A `bot compare` run of a commit against its parent.", exists=True, file_okay=False)],
    db: DbOpt = Path("benchwatch-history.db"),
    alpha: AlphaOpt = 0.01,
    threshold: ThresholdOpt = 0.03,
    warmup: WarmupOpt = 1,
) -> None:
    """Add a comparison run to the history database."""
    rec = store.record(db, run_dir, Params(alpha=alpha, threshold=threshold, warmup=warmup))
    console.print(f"{'replaced' if rec.replaced else 'recorded'} {rec.sha[:7]}: {rec.benchmarks} benchmarks in {db}")


@app.command()
def history(
    benchmark: Annotated[Optional[str], typer.Argument(help="Benchmark to show. Omit for a summary of all.")] = None,
    db: DbOpt = Path("benchwatch-history.db"),
    cpu_model: Annotated[Optional[str], typer.Option(help="Series to use. Default: the CPU model with the most runs.")] = None,
    threshold: ThresholdOpt = 0.03,
    alpha: AlphaOpt = 0.01,
    window: Annotated[int, typer.Option(help="Commits compared on each side of a candidate changepoint.")] = 10,
    plot: Annotated[Optional[Path], typer.Option(help="Write a trend chart (PNG) for BENCHMARK; needs the 'plot' extra.")] = None,
    theme: Annotated[str, typer.Option(help="Chart theme: light or dark.")] = "light",
) -> None:
    """Show benchmark trends on main and detect step changes across commits."""
    if not db.exists():
        raise typer.BadParameter(f"{db} does not exist; record runs with `bot record` first")
    models = store.cpu_models(db)
    df = store.load_history(db, benchmark, cpu_model)
    if df.empty:
        console.print("no history" + (f" for {benchmark}" if benchmark else ""))
        raise typer.Exit(code=1)
    model = df["cpu_model"].iloc[0]
    others = [m for m, _ in models if m != model]
    console.print(f"[dim]series: {model}" + (f"; also recorded on: {', '.join(others)}" if others else "") + "[/]")

    def detect(series):
        return changepoint.find_changepoints(series["median_ns"].to_numpy(), window=window,
                                             alpha=alpha, threshold=threshold)

    if benchmark is None:
        report.render_history_summary({name: (g, detect(g)) for name, g in df.groupby("benchmark", sort=False)},
                                      console)
        return
    cps = detect(df)
    report.render_history(benchmark, df, cps, console)
    if plot:
        from benchwatch import plot as plotting
        plotting.render_history(benchmark, df, cps, plot, theme)
        console.print(f"wrote {plot}")


RepoOpt = Annotated[Optional[str], typer.Option("--repo", help="owner/name. Default: $GITHUB_REPOSITORY.")]
HeadShaOpt = Annotated[str, typer.Option(help="Head commit SHA as reported by GitHub (trusted).")]
TargetUrlOpt = Annotated[Optional[str], typer.Option(help="Link shown on the commit status.")]


@app.command()
def publish(
    artifact_dir: Annotated[Path, typer.Argument(help="Downloaded benchmark artifact (pr.json, results.json, comment.md).")],
    head_sha: HeadShaOpt,
    conclusion: Annotated[str, typer.Option(help="Conclusion of the benchmark workflow run.")] = "success",
    target_url: TargetUrlOpt = None,
    repo: RepoOpt = None,
) -> None:
    """Post or update the PR comment and set the commit status (CI use; needs GITHUB_TOKEN)."""
    try:
        console.print(github.publish(github.from_env(repo), head_sha, conclusion, artifact_dir, target_url))
    except (github.GitHubError, OSError, KeyError, ValueError) as e:
        console.print(f"[bold red]error:[/] {e}")
        raise typer.Exit(code=2)


@app.command()
def pending(head_sha: HeadShaOpt, target_url: TargetUrlOpt = None, repo: RepoOpt = None) -> None:
    """Mark the commit status as pending while benchmarks run (CI use; needs GITHUB_TOKEN)."""
    try:
        github.from_env(repo).set_status(head_sha, "pending", "Benchmarks running", target_url)
    except github.GitHubError as e:
        console.print(f"[bold red]error:[/] {e}")
        raise typer.Exit(code=2)


@app.command()
def clean(repo: Annotated[Path, typer.Option(help="Repository whose cache to remove.")] = Path(".")) -> None:
    """Remove cached worktrees and builds."""
    root = runner.repo_root(repo)
    cache = root / CACHE_DIRNAME
    worktrees = cache / "worktrees"
    if worktrees.exists():
        for wt in worktrees.iterdir():
            try:
                runner.git(root, "worktree", "remove", "--force", str(wt))
            except runner.RunnerError:
                pass  # already detached from git; deleted below
    shutil.rmtree(cache, ignore_errors=True)
    runner.git(root, "worktree", "prune")
    console.print(f"removed {cache}")
