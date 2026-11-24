"""Compare renderer-only workloads in fresh development and compiled processes."""

import argparse
import hashlib
import json
import math
import os
import platform
import random
import statistics
import subprocess
from pathlib import Path

SCENARIOS = ("text", "row", "move", "swap", "rotate")
CASES = tuple(f"{scenario}-{width}" for scenario in SCENARIOS for width in (100, 500))


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate(result, revision):
    if result.get("bun") != revision:
        raise ValueError("Wrong runtime revision")
    rows = result.get("results")
    if not isinstance(rows, list) or len(rows) != len(CASES):
        raise ValueError("Wrong number of benchmark cases")
    metrics = {}
    for row in rows:
        case = f"{row.get('scenario')}-{row.get('rows')}"
        value = row.get("p50Ms")
        if (
            case not in CASES
            or case in metrics
            or row.get("samples") != 2000
            or type(value) not in (int, float)
            or not math.isfinite(value)
            or value <= 0
        ):
            raise ValueError("Invalid or duplicate benchmark case")
        metrics[case] = value
    return metrics


def main():
    parser = argparse.ArgumentParser()
    for name in ("base-source", "candidate-source", "bun", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("base-aot", "candidate-aot"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--base-commit", required=True)
    parser.add_argument("--candidate-commit", required=True)
    parser.add_argument("--bun-revision", required=True)
    args = parser.parse_args()
    if bool(args.base_aot) != bool(args.candidate_aot):
        raise ValueError("Both compiled clients are required together")
    names = ["base_source", "candidate_source", "bun"]
    if args.base_aot:
        names += ["base_aot", "candidate_aot"]
    paths = {name: getattr(args, name).resolve(strict=True) for name in names}
    fixture = "benchmarks/renderer/commit.ts"
    if digest(paths["base_source"] / fixture) != digest(
        paths["candidate_source"] / fixture
    ):
        raise ValueError("Benchmark fixtures differ")
    frozen = {
        name: digest(paths[name]) for name in names if not name.endswith("_source")
    }
    frozen["fixture"] = digest(paths["base_source"] / fixture)
    for variant in ("base", "candidate"):
        frozen[variant + "_renderer"] = digest(
            paths[variant + "_source"] / "packages/renderer/src/native-tree.ts"
        )
    output = args.output.resolve()
    output.mkdir(parents=True)
    report = {
        "status": "running",
        "scope": "Renderer in-process fake-host commit timings; excludes IPC, native host, input and presentation. Independent units are fresh processes.",
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "runner_image": os.environ.get("ImageVersion"),
        "base_commit": args.base_commit,
        "candidate_commit": args.candidate_commit,
        "sha256": frozen,
        "trials": [],
    }
    try:
        for mode in ("development", "aot") if args.base_aot else ("development",):
            plan = [
                ("warmup", 0, variant, variant) for variant in ("base", "candidate")
            ]
            for stage, count in (("aa", 6), ("paired", 12)):
                for index in range(count):
                    order = (
                        ("base", "candidate")
                        if index % 2 == 0
                        else ("candidate", "base")
                    )
                    plan.extend(
                        (stage, index, label, "base" if stage == "aa" else label)
                        for label in order
                    )
            for stage, index, label, actual in plan:
                source = paths[actual + "_source"]
                command = (
                    [str(paths["bun"]), str(source / fixture)]
                    if mode == "development"
                    else [str(paths[actual + "_aot"])]
                ) + ["100", "500"]
                row = {
                    "mode": mode,
                    "stage": stage,
                    "pair": index,
                    "label": label,
                    "actual": actual,
                    "command": command,
                }
                report["trials"].append(row)
                try:
                    proc = subprocess.run(
                        command,
                        cwd=source,
                        text=True,
                        capture_output=True,
                        timeout=120,
                        check=False,
                    )
                    row.update(
                        exit=proc.returncode, stdout=proc.stdout, stderr=proc.stderr
                    )
                    if proc.returncode:
                        raise ValueError(f"Child exited {proc.returncode}")
                    row["metrics"] = validate(
                        json.loads(proc.stdout), args.bun_revision
                    )
                    if any(
                        digest(paths[name]) != frozen[name]
                        for name in names
                        if not name.endswith("_source")
                    ):
                        raise ValueError("Executable changed during collection")
                    if (
                        digest(source / fixture) != frozen["fixture"]
                        or digest(source / "packages/renderer/src/native-tree.ts")
                        != frozen[actual + "_renderer"]
                    ):
                        raise ValueError("Source changed during collection")
                    row["status"] = "passed"
                except Exception as error:
                    row["status"] = "failed"
                    row["error"] = f"{type(error).__name__}: {error}"
                    raise
                finally:
                    (output / "summary.json").write_text(
                        json.dumps(report, indent=2) + "\n"
                    )
        rng = random.Random(20261124)
        report["comparisons"] = []
        for mode in ("development", "aot") if args.base_aot else ("development",):
            for stage, count in (("aa", 6), ("paired", 12)):
                trials = [
                    row
                    for row in report["trials"]
                    if row["mode"] == mode and row["stage"] == stage
                ]
                for case in CASES:
                    ratios = []
                    for index in range(count):
                        rows = {
                            row["label"]: row for row in trials if row["pair"] == index
                        }
                        ratios.append(
                            rows["candidate"]["metrics"][case]
                            / rows["base"]["metrics"][case]
                        )
                    boot = sorted(
                        statistics.median(rng.choices(ratios, k=count))
                        for _ in range(2000)
                    )
                    report["comparisons"].append(
                        {
                            "mode": mode,
                            "stage": stage,
                            "case": case,
                            "pairs": count,
                            "median_ratio": statistics.median(ratios),
                            "bootstrap_95_percent": [boot[50], boot[1949]],
                            "candidate_wins": sum(value < 1 for value in ratios),
                        }
                    )
        report["status"] = "passed"
    except Exception as error:
        report["status"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        (output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
