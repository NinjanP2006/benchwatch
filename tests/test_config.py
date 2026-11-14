import json

import pytest
from typer.testing import CliRunner

from benchwatch.cli import app
from benchwatch.config import ConfigError, default_map, load
from test_store import fake_run


def write(tmp_path, text):
    path = tmp_path / ".benchbot.yml"
    path.write_text(text)
    return path


def test_load_and_map_to_command_defaults(tmp_path):
    cfg = load(write(tmp_path, 'rounds: 20\nthreshold: 0.05\nfilter: "BM_Sort"\nignore: ["Strided"]\nalpha: 0.05\n'))
    dm = default_map(cfg)
    assert dm["compare"] == {"rounds": 20, "threshold": 0.05, "benchmark_filter": "BM_Sort",
                             "ignore": ["Strided"], "alpha": 0.05}
    assert dm["history"] == {"threshold": 0.05, "alpha": 0.05}
    assert "rounds" not in dm["analyze"]


def test_ints_are_accepted_for_floats(tmp_path):
    assert load(write(tmp_path, "min_time: 1\n")) == {"min_time": 1.0}


def test_empty_file_and_null_values_are_fine(tmp_path):
    assert load(write(tmp_path, "")) == {}
    assert load(write(tmp_path, "filter: null\n")) == {}


@pytest.mark.parametrize("text, message", [
    ("roundz: 3\n", "unknown key"),
    ("rounds: fifteen\n", "expected int"),
    ("rounds: true\n", "expected int"),
    ("ignore: BM_A\n", "list of strings"),
    ("alpha: 1.5\n", "between 0 and 1"),
    ("rounds: 5\nwarmup: 5\n", "smaller than rounds"),
    ("filter: '(unclosed'\n", "invalid regex"),
    ("ignore: ['ok', '[bad']\n", r"ignore\[1\]"),
    ("- a\n- b\n", "mapping"),
])
def test_invalid_configs_are_rejected_with_a_reason(tmp_path, text, message):
    with pytest.raises(ConfigError, match=message):
        load(write(tmp_path, text))


def test_cli_uses_config_and_flags_override_it(tmp_path):
    run_dir = fake_run(tmp_path / "run", "b" * 40, "a" * 40, "2026-01-01T00:00:00+00:00", 102.0)
    cfg = write(tmp_path, "threshold: 0.01\nignore: ['BM_B']\n")
    runner = CliRunner()

    out = tmp_path / "a.json"
    result = runner.invoke(app, ["--config", str(cfg), "analyze", str(run_dir), "--out", str(out),
                                 "--no-fail-on-regression"])
    assert result.exit_code == 0, result.output
    data = json.loads(out.read_text())
    assert data["params"]["threshold"] == 0.01                      # from the file
    assert [r["benchmark"] for r in data["results"]] == ["BM_A"]   # BM_B ignored
    assert data["results"][0]["verdict"] == "regression"           # +2% > 1% threshold

    out2 = tmp_path / "b.json"
    result = runner.invoke(app, ["--config", str(cfg), "analyze", str(run_dir), "--out", str(out2),
                                 "--threshold", "0.05", "--no-fail-on-regression"])
    assert result.exit_code == 0, result.output
    data = json.loads(out2.read_text())
    assert data["params"]["threshold"] == 0.05                      # the flag wins
    assert data["results"][0]["verdict"] == "unchanged"


def test_cli_reports_bad_config(tmp_path):
    cfg = write(tmp_path, "roundz: 3\n")
    result = CliRunner().invoke(app, ["--config", str(cfg), "analyze", str(tmp_path)])
    assert result.exit_code == 2
    assert "unknown key" in result.output
