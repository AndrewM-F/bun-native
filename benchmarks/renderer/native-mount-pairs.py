"""Compare source-matched renderer clients and release native hosts on Linux."""

import argparse
import hashlib
import json
import math
import os
import platform
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.quality.native_harness.bridge_pairs import run_owned

CASES = ("mount-42", "mount-128")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate(result, host, bun_revision):
    if result.get("status") != "passed" or result.get("host") != str(host):
        raise ValueError("Wrong host or failed workload")
    if result.get("bunRevision") != bun_revision or set(
        result.get("samples", {})
    ) != set(CASES):
        raise ValueError("Wrong runtime or incomplete samples")
    for values in result["samples"].values():
        if len(values) != 50 or any(
            type(value) not in (int, float) or not math.isfinite(value) or value <= 0
            for value in values
        ):
            raise ValueError("Expected 50 positive acknowledgement samples per case")
    return {key: statistics.median(result["samples"][key]) for key in CASES}


def main():
    parser = argparse.ArgumentParser()
    for name in (
        "base-source",
        "candidate-source",
        "base-host",
        "candidate-host",
        "base-aot",
        "candidate-aot",
        "bun",
        "output",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--base-commit", required=True)
    parser.add_argument("--candidate-commit", required=True)
    parser.add_argument("--bun-revision", required=True)
    args = parser.parse_args()
    paths = {
        name: getattr(args, name).resolve(strict=True)
        for name in (
            "base_source",
            "candidate_source",
            "base_host",
            "candidate_host",
            "base_aot",
            "candidate_aot",
            "bun",
        )
    }
    output = args.output.resolve()
    fixture = "benchmarks/renderer/native-mount.ts"
    if digest(paths["base_source"] / fixture) != digest(
        paths["candidate_source"] / fixture
    ):
        raise ValueError("Clients do not use the same benchmark fixture")
    frozen = {
        name: digest(paths[name])
        for name in ("base_host", "candidate_host", "base_aot", "candidate_aot", "bun")
    }
    frozen["base_renderer"] = digest(
        paths["base_source"] / "packages/renderer/src/native-tree.ts"
    )
    frozen["candidate_renderer"] = digest(
        paths["candidate_source"] / "packages/renderer/src/native-tree.ts"
    )
    frozen["fixture"] = digest(paths["base_source"] / fixture)
    output.mkdir(parents=True)
    report = {
        "status": "running",
        "scope": "Real native windows; mounts from staging to acknowledged native command, not physical input or display presentation. Each fresh process is an independent trial.",
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
        for mode in ("development", "aot"):
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
            for serial, (stage, index, label, actual) in enumerate(plan):
                directory = output / f"{mode}-{serial:02d}-{stage}-{label}"
                directory.mkdir()
                source = paths[actual + "_source"]
                command = (
                    [str(paths["bun"]), str(source / fixture)]
                    if mode == "development"
                    else [str(paths[actual + "_aot"])]
                )
                environment = os.environ.copy()
                host = paths[actual + "_host"]
                environment["BUN_NATIVE_HOST"] = str(host)
                environment.pop("BUN_NATIVE_EVIDENCE_LOG", None)
                environment.pop("BUN_NATIVE_EVIDENCE_NONCE", None)
                row = {
                    "mode": mode,
                    "stage": stage,
                    "pair": index,
                    "label": label,
                    "actual": actual,
                }
                report["trials"].append(row)
                try:
                    row["supervisor"] = run_owned(
                        command,
                        source,
                        directory / "process",
                        150,
                        expected_host=host,
                        environment=environment,
                    )
                    if row["supervisor"]["status"] != "passed":
                        raise ValueError("Process supervision or cleanup failed")
                    result = json.loads((directory / "process/stdout.log").read_text())
                    row["metrics"] = validate(result, host, args.bun_revision)
                    row["samples"] = result["samples"]
                    if any(
                        digest(paths[name]) != frozen[name]
                        for name in (
                            "base_host",
                            "candidate_host",
                            "base_aot",
                            "candidate_aot",
                            "bun",
                        )
                    ):
                        raise ValueError("An executable changed during collection")
                    if (
                        digest(source / fixture) != frozen["fixture"]
                        or digest(source / "packages/renderer/src/native-tree.ts")
                        != frozen[actual + "_renderer"]
                    ):
                        raise ValueError("Measured source changed during collection")
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
        for mode in ("development", "aot"):
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
