from benchwatch.report import MARKER, status_summary, to_markdown
from benchwatch.stats import Analysis, BenchmarkResult, Params, Verdict

META = {"base": {"sha": "1" * 40}, "head": {"sha": "2" * 40}, "config": {"rounds": 15},
        "host": {"platform": "Linux-6.8"}}


def result(name, ratio, verdict):
    return BenchmarkResult(benchmark=name, n=14, base_median_ns=1000.0, head_median_ns=1000.0 * ratio,
                           ratio=ratio, ci_low=ratio - 0.01, ci_high=ratio + 0.01, p_value=0.001,
                           p_adjusted=0.002, outliers=0, verdict=verdict)


def analysis(*results):
    return Analysis(params=Params(), results=list(results))


def test_regressions_lead_and_others_are_collapsed():
    md = to_markdown(analysis(result("BM_A", 1.20, Verdict.REGRESSION),
                              result("BM_B", 1.00, Verdict.UNCHANGED),
                              result("BM_C", 1.02, Verdict.INCONCLUSIVE)), META, {"num_cpus": 4})
    assert md.startswith(MARKER)
    assert "### Benchwatch: 🔴 1 regression\n" in md
    head, details = md.split("<details>", 1)
    assert "`BM_A`" in head and "**+20.0%**" in head
    assert "`BM_B`" not in head
    assert "2 other benchmarks (1 unchanged, 1 inconclusive)" in details
    assert "Base `1111111` vs head `2222222`" in md
    assert "4 CPUs" in md


def test_clean_run_headline():
    md = to_markdown(analysis(result("BM_A", 1.0, Verdict.UNCHANGED)))
    assert "✅ No significant changes" in md
    assert "| Benchmark |" in md.split("<details>", 1)[1]  # table only inside the collapsed section


def test_status_summary_names_worst_regression():
    a = analysis(result("BM_small", 1.05, Verdict.REGRESSION), result("BM_big", 1.50, Verdict.REGRESSION))
    assert status_summary(a) == "2 regressions; worst BM_big +50.0%"
    assert status_summary(analysis(result("BM_A", 1.0, Verdict.UNCHANGED))) == "No regressions across 1 benchmark"
