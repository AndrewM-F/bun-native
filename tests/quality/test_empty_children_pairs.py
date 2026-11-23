"""The performance collector must reject incomplete or malformed runs."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

MODULE_PATH = Path(__file__).resolve().parents[2] / "benchmarks/empty-children-pairs.py"
SPEC = importlib.util.spec_from_file_location("empty_children_pairs", MODULE_PATH)
assert SPEC and SPEC.loader
pairs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pairs)


def valid_rows():
    rows = [
        {
            "kind": "prepare",
            "shape": shape,
            "nodes": n,
            "iterations": 100 if n == 1024 else 300,
            "elapsed_ns": 100,
        }
        for shape in ("flat", "grouped")
        for n in (1, 16, 128, 1024)
    ]
    rows.extend(
        {
            "kind": "concurrent",
            "threads": n,
            "nodes": 128,
            "iterations_per_thread": 1000,
            "elapsed_ns": 100,
        }
        for n in (1, 2, 4)
    )
    return rows


def test_rejects_missing_duplicate_and_wrong_workload(monkeypatch):
    rows = valid_rows()
    process = SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(pairs.subprocess, "run", lambda *args, **kwargs: process)
    for invalid in (
        rows[:-1],
        rows[:-1] + [rows[0]],
        [{**rows[0], "iterations": 2}] + rows[1:],
    ):
        process.stdout = "\n".join(json.dumps(row) for row in invalid)
        with pytest.raises(ValueError):
            pairs.measure(Path("unused"))
    process.stdout = "\n".join(json.dumps(row) for row in reversed(rows))
    assert len(pairs.measure(Path("unused"))) == 11
    process.returncode = 1
    with pytest.raises(ValueError):
        pairs.measure(Path("unused"))


def test_summary_preserves_ratios_and_fixed_seed():
    base = valid_rows()
    candidate = [{**row, "elapsed_ns": 80} for row in base]
    samples = [{"base": base, "candidate": candidate} for _ in range(5)]
    result = pairs.summarize(samples)
    assert result == pairs.summarize(samples)
    assert all(
        row["median_ratio"] == 0.8 and row["candidate_wins"] == 5 for row in result
    )
