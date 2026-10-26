"""Command-line entry point: `bot compare`, `bot analyze`, `bot clean`."""

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

from benchwatch import github, parse, report, runner
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
    min_time: Annotated[float, typer.Option(help="Google Benchmark min time per benchmark per run, seconds.")] = 0.1,
    benchmark_filter: Annotated[Optional[str], typer.Option("--filter", help="Regex passed to --benchmark_filter.")] = None,
    cmake_arg: Annotated[Optional[list[str]], typer.Option(help="Extra CMake arg for both sides (repeatable), e.g. a compiler launcher.")] = None,
    base_cmake_arg: Annotated[Optional[list[str]], typer.Option(help="Extra CMake arg for base (repeatable). Use the --opt=value form.")] = None,
    head_cmake_arg: Annotated[Optional[list[str]], typer.Option(help="Extra CMake arg for head (repeatable). Use the --opt=value form.")] = None,
    repo: Annotated[Path, typer.Option(help="Repository to benchmark.")] = Path("."),
    source_dir: Annotated[str, typer.Option(help="CMake source directory, relative to the repo root.")] = "target",
    bench_target: Annotated[str, typer.Option(help="CMake target of the benchmark executable.")] = "bench",
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
        base_side = runner.Side("base", base, base_sha, shared + tuple(base_cmake_arg or ()))
        head_side = runner.Side("head", head, head_sha, shared + tuple(head_cmake_arg or ()))
        if base_side.sha == head_side.sha and base_side.cmake_args == head_side.cmake_args:
            console.print("[yellow]base and head are identical: this is an A/A comparison[/]")

        config = runner.RunConfig(rounds=rounds, min_time_s=min_time, benchmark_filter=benchmark_filter,
                                  source_dir=source_dir, bench_target=bench_target)
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
