"""Run fresh-process A/A and AB/BA protocol preparation controls."""

import argparse
import hashlib
import json
import os
import platform
import random
import statistics
import subprocess
from pathlib import Path


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def measure(path):
    process = subprocess.run(
        [str(path)], capture_output=True, text=True, timeout=180, check=False
    )
    rows = [json.loads(line) for line in process.stdout.splitlines()]
    expected = {
        (shape, size) for shape in ("flat", "grouped") for size in (1, 16, 128, 1024)
    }
    actual = {
        (r.get("shape"), r.get("nodes")) for r in rows if r.get("kind") == "prepare"
    }
    concurrent = {r.get("threads") for r in rows if r.get("kind") == "concurrent"}
    if (
        process.returncode
        or len(rows) != 11
        or actual != expected
        or concurrent != {1, 2, 4}
    ):
        raise ValueError(
            f"Invalid benchmark output: exit={process.returncode}; stderr={process.stderr[-2000:]}"
        )
    if any(type(r.get("elapsed_ns")) is not int or r["elapsed_ns"] <= 0 for r in rows):
        raise ValueError("Every elapsed time must be a positive integer")
    for row in rows:
        if row["kind"] == "prepare" and row.get("iterations") != (
            100 if row["nodes"] == 1024 else 300
        ):
            raise ValueError("Unexpected preparation iteration count")
        if row["kind"] == "concurrent" and (
            row.get("iterations_per_thread") != 1000 or row.get("nodes") != 128
        ):
            raise ValueError("Unexpected concurrent workload")
    return sorted(
        rows,
        key=lambda row: (
            row["kind"],
            row.get("shape", ""),
            row.get("nodes", 0),
            row.get("threads", 0),
        ),
    )


def summarize(pairs):
    result = []
    rng = random.Random(20261123)
    for index, first in enumerate(pairs[0]["base"]):
        ratios = [
            pair["candidate"][index]["elapsed_ns"] / pair["base"][index]["elapsed_ns"]
            for pair in pairs
        ]
        boot = sorted(
            statistics.median(rng.choices(ratios, k=len(ratios))) for _ in range(2000)
        )
        result.append(
            {
                "case": {k: v for k, v in first.items() if k != "elapsed_ns"},
                "median_ratio": statistics.median(ratios),
                "bootstrap_95_percent": [boot[50], boot[1949]],
                "candidate_wins": sum(r < 1 for r in ratios),
            }
        )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--baseline-source", required=True)
    parser.add_argument("--candidate-source", required=True)
    parser.add_argument("--pairs", type=int, default=20)
    parser.add_argument("--aa-pairs", type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.pairs <= 40 or not 1 <= args.aa_pairs <= 40:
        parser.error("pair counts must be between 1 and 40")
    base = args.baseline.resolve(strict=True)
    candidate = args.candidate.resolve(strict=True)
    output = args.output.resolve()
    if output.exists():
        raise ValueError("Refusing to overwrite previous evidence")
    output.mkdir(parents=True)
    report = {
        "scope": "Fresh-process protocol preparation; no native host, IPC, presentation or input measurement. Allocation counting is not enabled.",
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "runner_image": os.environ.get("ImageVersion"),
        "baseline_source": args.baseline_source,
        "candidate_source": args.candidate_source,
        "baseline_sha256": digest(base),
        "candidate_sha256": digest(candidate),
        "controls": {},
        "complete": False,
    }
    try:
        measure(base)
        measure(candidate)
        for name, reference, count in (
            ("aa", base, args.aa_pairs),
            ("paired", candidate, args.pairs),
        ):
            pairs = []
            report["controls"][name] = {"pairs": pairs}
            for index in range(count):
                order = (
                    ("base", "candidate") if index % 2 == 0 else ("candidate", "base")
                )
                pair = {"index": index, "order": order}
                pairs.append(pair)
                for variant in order:
                    pair[variant] = measure(base if variant == "base" else reference)
                (output / "pairs.json").write_text(json.dumps(report, indent=2) + "\n")
            report["controls"][name]["summary"] = summarize(pairs)
        report["complete"] = True
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        (output / "pairs.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
