"""Compare real native-host mount acknowledgements with A/A and AB/BA runs."""

import argparse
import hashlib
import json
import math
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.quality.native_harness.bridge_pairs import SEMANTICS, read_json, run_owned


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_result(result, mode, host_hash, source):
    if result.get("status") != "passed" or result.get("nativeExitCode") != 0:
        raise ValueError("Native workload or shutdown failed")
    if result.get("semanticChecks") != SEMANTICS:
        raise ValueError("Native semantic checks are incomplete")
    if (
        result["execution"]["mode"] != mode
        or result["nativeHost"]["sha256"] != host_hash
    ):
        raise ValueError("Wrong execution mode or host")
    if result["source"]["commit"] != source or result["methodology"]["instrumentation"]:
        raise ValueError("Wrong source or instrumented run")
    mount = result["mountBatches"]
    samples = mount["samplesMs"]
    if (
        mount["count"] != 8
        or len(samples) != 8
        or any(
            type(value) not in (int, float) or not math.isfinite(value) or value <= 0
            for value in samples
        )
    ):
        raise ValueError("Expected eight positive mount acknowledgements")
    return sum(samples)


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
    if output.exists():
        raise ValueError("Refusing to overwrite previous observations")
    if digest(paths["base_source"] / "benchmarks/bridge.ts") != digest(
        paths["candidate_source"] / "benchmarks/bridge.ts"
    ):
        raise ValueError("The two bridge clients are not identical")
    output.mkdir(parents=True)
    report = {
        "status": "running",
        "scope": "Real native windows and Bun-to-host mount acknowledgements, not display presentation or physical input. Each process uses its own source-matched host and AOT package.",
        "base_commit": args.base_commit,
        "candidate_commit": args.candidate_commit,
        "host_sha256": {
            "base": digest(paths["base_host"]),
            "candidate": digest(paths["candidate_host"]),
        },
        "bridge_sha256": digest(paths["candidate_source"] / "benchmarks/bridge.ts"),
        "trials": [],
    }
    try:
        # One full warmup per variant and mode; then four A/A and eight AB/BA
        # measured pairs per mode. No failed attempt is retried or omitted.
        for mode in ("development", "aot"):
            plan = [
                ("warmup", 0, variant, variant) for variant in ("base", "candidate")
            ]
            for stage, count in (("aa", 4), ("paired", 8)):
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
                host = paths[actual + "_host"]
                package = paths[actual + "_aot"]
                command = (
                    [str(paths["bun"]), str(source / "benchmarks/bridge.ts")]
                    if mode == "development"
                    else [str(package / "bridge")]
                )
                command += [
                    "--mode",
                    mode,
                    "--host",
                    str(host),
                    "--host-profile",
                    "release",
                    "--source",
                    str(source),
                    "--output",
                    str(directory / "workload"),
                ]
                if mode == "aot":
                    command += ["--aot-manifest", str(package / "manifest.json")]
                row = {
                    "mode": mode,
                    "stage": stage,
                    "pair": index,
                    "label": label,
                    "actual": actual,
                }
                report["trials"].append(row)
                try:
                    supervisor = run_owned(
                        command, source, directory / "process", 150, expected_host=host
                    )
                    row["supervisor"] = supervisor
                    if supervisor["status"] != "passed":
                        raise ValueError("Process supervision or cleanup failed")
                    result = read_json(directory / "workload/result.json")
                    row["mount_total_ms"] = check_result(
                        result,
                        mode,
                        report["host_sha256"][actual],
                        args.base_commit if actual == "base" else args.candidate_commit,
                    )
                    row["status"] = "passed"
                except Exception as error:
                    row["status"] = "failed"
                    row["error"] = f"{type(error).__name__}: {error}"
                    raise
                finally:
                    (output / "summary.json").write_text(
                        json.dumps(report, indent=2) + "\n"
                    )
        rng = random.Random(20261123)
        report["comparisons"] = []
        for mode in ("development", "aot"):
            for stage in ("aa", "paired"):
                trials = [
                    x
                    for x in report["trials"]
                    if x["mode"] == mode and x["stage"] == stage
                ]
                count = 4 if stage == "aa" else 8
                ratios = []
                for index in range(count):
                    rows = {x["label"]: x for x in trials if x["pair"] == index}
                    ratios.append(
                        rows["candidate"]["mount_total_ms"]
                        / rows["base"]["mount_total_ms"]
                    )
                boot = sorted(
                    statistics.median(rng.choices(ratios, k=count)) for _ in range(2000)
                )
                report["comparisons"].append(
                    {
                        "mode": mode,
                        "stage": stage,
                        "pairs": count,
                        "median_ratio": statistics.median(ratios),
                        "bootstrap_95_percent": [boot[50], boot[1949]],
                        "candidate_wins": sum(x < 1 for x in ratios),
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
