"""`.benchbot.yml`: repository-level defaults for every command.

The file is flat; each key becomes the default of the matching option on the
commands listed below. Precedence: command-line flag > config file > built-in
default. Example:

    rounds: 20
    threshold: 0.05
    filter: "BM_Sort|BM_Parse"        # run only these on PRs
    ignore: ["BM_StridedSum/67108864"]  # run, but never judge (too noisy)
"""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_PATH = Path(".benchbot.yml")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Key:
    kind: type            # int, float, str, or list (of str)
    commands: tuple[str, ...]
    param: str | None = None  # CLI parameter name when it differs from the key
    help: str = ""


KEYS: dict[str, Key] = {
    "source_dir": Key(str, ("compare", "collect"), help="CMake source directory, relative to the repo root"),
    "bench_target": Key(str, ("compare", "collect"), help="CMake target of the benchmark executable"),
    "cmake_args": Key(list, ("compare", "collect"), param="cmake_arg", help="extra CMake arguments for every build"),
    "main_branch": Key(str, ("compare",), param="main", help="branch used for the default merge-base"),
    "rounds": Key(int, ("compare",), help="interleaved rounds per comparison"),
    "warmup": Key(int, ("compare", "analyze", "record", "simulate"), help="leading rounds to discard"),
    "min_time": Key(float, ("compare", "collect"), help="Google Benchmark min time per benchmark per run, s"),
    "filter": Key(str, ("compare", "collect"), param="benchmark_filter", help="regex of benchmarks to run"),
    "ignore": Key(list, ("compare", "analyze", "record"), help="regexes of benchmarks to leave out of verdicts"),
    "alpha": Key(float, ("compare", "analyze", "record", "history", "simulate"), help="family-wise significance level"),
    "threshold": Key(float, ("compare", "analyze", "record", "history"), help="smallest change that counts (0.03 = 3%)"),
    "window": Key(int, ("history",), help="commits on each side of a candidate level shift"),
}


def _check(name: str, value, key: Key):
    if key.kind is list:
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ConfigError(f"{name}: expected a list of strings")
        return value
    if key.kind is float and isinstance(value, int) and not isinstance(value, bool):
        value = float(value)
    if not isinstance(value, key.kind) or isinstance(value, bool):
        raise ConfigError(f"{name}: expected {key.kind.__name__}, got {type(value).__name__}")
    return value


def load(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as e:
        raise ConfigError(f"cannot read {path}: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a mapping of keys to values")

    unknown = sorted(set(data) - set(KEYS))
    if unknown:
        raise ConfigError(f"{path}: unknown key(s) {', '.join(unknown)}; valid keys: {', '.join(KEYS)}")
    cfg = {name: _check(name, value, KEYS[name]) for name, value in data.items() if value is not None}

    if "alpha" in cfg and not 0 < cfg["alpha"] < 1:
        raise ConfigError("alpha: must be between 0 and 1")
    if "threshold" in cfg and not 0 <= cfg["threshold"] < 1:
        raise ConfigError("threshold: must be at least 0 and below 1")
    if "rounds" in cfg and cfg["rounds"] < 2:
        raise ConfigError("rounds: must be at least 2")
    if "warmup" in cfg and cfg["warmup"] < 0:
        raise ConfigError("warmup: must not be negative")
    if "warmup" in cfg and "rounds" in cfg and cfg["warmup"] >= cfg["rounds"]:
        raise ConfigError("warmup: must be smaller than rounds")
    if "window" in cfg and cfg["window"] < 2:
        raise ConfigError("window: must be at least 2")
    patterns = [("filter", cfg["filter"])] if "filter" in cfg else []
    patterns += [(f"ignore[{i}]", p) for i, p in enumerate(cfg.get("ignore", []))]
    for name, pattern in patterns:
        try:
            re.compile(pattern)
        except re.error as e:
            raise ConfigError(f"{name}: invalid regex {pattern!r}: {e}") from e
    return cfg


def default_map(cfg: dict) -> dict[str, dict]:
    """Click default_map: {command: {parameter: default}}."""
    out: dict[str, dict] = {}
    for name, value in cfg.items():
        key = KEYS[name]
        for command in key.commands:
            out.setdefault(command, {})[key.param or name] = value
    return out
