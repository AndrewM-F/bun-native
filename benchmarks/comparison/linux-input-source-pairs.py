"""Alternating exact-source native input observations on one Linux X11 session.

The same driver verifies the application event, complete native paint trees and
unforced cleanup for both artifacts. This measures observed paint records, not
hardware presentation. Invalid launches are retained and invalidate the run.
"""

import argparse
import hashlib
import json
import os
import platform
import random
import statistics
import subprocess
import sys
import uuid
from pathlib import Path

STAGES = (("aa", 12), ("paired", 24))


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def interval(values, seed=675, rounds=5000):
    if len(values) < 3:
        raise ValueError("At least three valid pairs are required")
    randomizer = random.Random(seed)
    ordered = sorted(
        statistics.median(randomizer.choices(values, k=len(values)))
        for _ in range(rounds)
    )
    return [ordered[int(rounds * 0.025)], ordered[int(rounds * 0.975) - 1]]


def expected(bun, source):
    code = """import {expectedNodes, INPUT_LABEL, WINDOW_TITLE} from "./benchmarks/solid/workload.ts";
const rows = Array.from({length:32},(_,id)=>({id,text:`Row ${id}`}));
console.log(JSON.stringify({title:WINDOW_TITLE,initial:{type:"rendered",stage:"native-paint",window_id:1,tree_revision:1,nodes:expectedNodes(rows,"Initial")},changed:{type:"rendered",stage:"native-paint",window_id:1,nodes:expectedNodes(rows,INPUT_LABEL)}}));"""
    result = subprocess.run(
        [str(bun), "-e", code],
        cwd=source,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(result.stdout)


def validate(driver, app, exit_code):
    if exit_code or driver.get("status") != "passed" or app.get("status") != "passed":
        raise ValueError("Input driver or application failed")
    if app.get("workload") != {"scenario": "input-latency", "rows": 32}:
        raise ValueError("Input workload differs")
    if (
        app.get("declaredMode") != "aot"
        or app.get("bunRevision") != "b1007f1177fd402fae67387b8548cae5ae9b5707"
    ):
        raise ValueError("Unexpected runtime revision or mode")
    if app.get("input", {}).get("clicks") != 1:
        raise ValueError("Expected exactly one acknowledged click")
    cleanup = app.get("cleanup")
    if not isinstance(cleanup, dict) or any(value != 0 for value in cleanup.values()):
        raise ValueError("Application ownership was not fully cleaned up")
    observer = driver.get("measurements", {}).get("native_paint_file_observation", {})
    value = observer.get("command_start_to_paint_observed_ms")
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not 0 < value < 120_000
    ):
        raise ValueError("Missing or invalid observed paint timing")
    if observer.get("paint", {}).get("complete_expected_tree_matched") is not True:
        raise ValueError("Expected native paint tree was not matched")
    if driver.get("paint_observer_cleanup", {}).get("reader_stopped") is not True:
        raise ValueError("Paint observer did not stop")
    if driver.get("paint_observer_cleanup", {}).get("open_descriptors") != 0:
        raise ValueError("Paint observer leaked descriptors")
    checks = driver.get("checks", {})
    if (
        any(
            checks.get(name) != "passed"
            for name in (
                "window",
                "app_input_event",
                "app_initial_render_report",
                "app_render_report",
                "native_paint_file_observation",
                "os_close",
            )
        )
        or checks.get("os_input") != "injected-through-XTest"
    ):
        raise ValueError("Required native input or paint check did not pass")
    if driver.get("cleanup", {}).get("forced_termination") is not False:
        raise ValueError("Application required forced termination")
    renderer = driver.get("renderer", {})
    if renderer.get("status") != "reported-by-native-window" or not isinstance(
        renderer.get("gpu"), dict
    ):
        raise ValueError("Native renderer identity is missing")
    return value, renderer["gpu"]


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
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    paths = {
        key: getattr(args, key).resolve(strict=True)
        for key in (
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
    output.mkdir(parents=False, exist_ok=False)
    fixtures = [
        paths[f"{variant}_source"] / "benchmarks/solid/direct.ts"
        for variant in ("base", "candidate")
    ]
    if sha(fixtures[0]) != sha(fixtures[1]):
        raise ValueError("Direct fixture source differs across the candidates")
    expectations = expected(paths["bun"], paths["candidate_source"])
    driver_path = paths["candidate_source"] / "scripts/quality/native-input-linux.py"
    artifacts = {
        variant: {
            "host": sha(paths[f"{variant}_host"]),
            "aot": sha(paths[f"{variant}_aot"]),
        }
        for variant in ("base", "candidate")
    }
    plan = {
        "baseCommit": "d67794d1bde2eeb3621f2cd1f96d1379ea87a400",
        "candidateCommit": "841ea02653a54ea7a3e2ccdc80dbac6520e3b686",
        "scope": "Same X11 session, pinned Bun and common driver; observed native paint record, not presentation. Historical and current hosts and core sources differ.",
        "fixtureSha256": sha(fixtures[0]),
        "workloadSha256": {
            variant: sha(paths[f"{variant}_source"] / "benchmarks/solid/workload.ts")
            for variant in ("base", "candidate")
        },
        "driverSha256": sha(driver_path),
        "bunSha256": sha(paths["bun"]),
        "artifacts": artifacts,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpuModels": sorted(
            {
                line.split(":", 1)[1].strip()
                for line in Path("/proc/cpuinfo").read_text().splitlines()
                if line.startswith("model name") and ":" in line
            }
        ),
        "cache": "OS page cache uncontrolled; each input launch is a fresh process",
        "ordering": "12 baseline/baseline pairs then 24 alternating baseline/candidate pairs",
        "expected": expectations,
    }
    (output / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    records = []
    renderer_identity = None
    for stage, count in STAGES:
        for trial in range(count):
            order = (
                ("base", "base")
                if stage == "aa"
                else (
                    ("base", "candidate") if trial % 2 == 0 else ("candidate", "base")
                )
            )
            for position, variant in enumerate(order):
                name = f"{stage}-{trial:02}-{position}-{variant}"
                path = output / name
                report = output / f"{name}-application.json"
                nonce = str(uuid.uuid4())
                host, aot = paths[f"{variant}_host"], paths[f"{variant}_aot"]
                if (
                    sha(host) != artifacts[variant]["host"]
                    or sha(aot) != artifacts[variant]["aot"]
                ):
                    raise ValueError("Executable changed during comparison")
                command = [
                    sys.executable,
                    str(driver_path),
                    "--output",
                    str(path),
                    "--mode",
                    "aot",
                    "--title",
                    expectations["title"],
                    "--timeout",
                    "30",
                    "--require-unforced-cleanup",
                    "--expect-initial-render",
                    json.dumps(expectations["initial"]),
                    "--expect-render",
                    json.dumps(expectations["changed"]),
                    "--expect-event",
                    json.dumps(
                        {
                            "type": "click",
                            "stage": "bun-application",
                            "target": "benchmark-fixture",
                            "adapter": "core",
                        }
                    ),
                    "--click",
                    "100",
                    "75",
                    "--",
                    str(aot),
                    "--host",
                    str(host),
                    "--output",
                    str(report),
                    "--nonce",
                    nonce,
                    "--mode",
                    "aot",
                    "--iterations",
                    "1000",
                    "--rotations",
                    "1000",
                    "--mounts",
                    "100",
                    "--rows",
                    "32",
                    "--input-latency",
                ]
                env = {
                    key: value
                    for key, value in os.environ.items()
                    if not key.startswith("BUN_NATIVE_EVIDENCE_")
                }
                env.update(BUN_NATIVE_HOST=str(host), BUN_NATIVE_HOST_PROFILE="release")
                record = {
                    "stage": stage,
                    "trial": trial,
                    "position": position,
                    "variant": variant,
                    "valid": False,
                    "loadAverageBeforeLaunch": Path("/proc/loadavg")
                    .read_text()
                    .strip(),
                }
                try:
                    child = subprocess.run(
                        command,
                        cwd=paths[f"{variant}_source"],
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=120,
                        check=False,
                    )
                    (output / f"{name}.stdout.txt").write_text(
                        child.stdout, encoding="utf-8"
                    )
                    (output / f"{name}.stderr.txt").write_text(
                        child.stderr, encoding="utf-8"
                    )
                    driver = json.loads((path / "result.json").read_text())
                    app = json.loads(report.read_text())
                    latency, renderer = validate(driver, app, child.returncode)
                    if renderer_identity is None:
                        renderer_identity = renderer
                    if renderer != renderer_identity:
                        raise ValueError("Renderer identity changed between launches")
                    record.update(valid=True, latencyMs=latency, renderer=renderer)
                except (
                    OSError,
                    ValueError,
                    KeyError,
                    TypeError,
                    subprocess.TimeoutExpired,
                ) as error:
                    record["error"] = str(error)
                records.append(record)
                (output / "records.json").write_text(
                    json.dumps(records, indent=2) + "\n"
                )
                print(json.dumps(record), flush=True)
                if not record["valid"]:
                    raise SystemExit(
                        "Launch failed; retained evidence and stopped the comparison"
                    )
    if not all(row["valid"] for row in records):
        raise SystemExit("At least one launch failed; all observations were retained")
    summaries = {}
    for stage, count in STAGES:
        ratios = []
        for trial in range(count):
            pair = [
                row
                for row in records
                if row["stage"] == stage and row["trial"] == trial
            ]
            if stage == "aa":
                ratios.append(pair[1]["latencyMs"] / pair[0]["latencyMs"])
            else:
                base = next(
                    row["latencyMs"] for row in pair if row["variant"] == "base"
                )
                candidate = next(
                    row["latencyMs"] for row in pair if row["variant"] == "candidate"
                )
                ratios.append(candidate / base)
        summaries[stage] = {
            "pairs": count,
            "medianRatio": statistics.median(ratios),
            "bootstrap95": interval(ratios),
            "candidateWins": sum(value < 1 for value in ratios),
        }
    (output / "summary.json").write_text(
        json.dumps(
            {"status": "passed", "plan": plan, "comparisons": summaries}, indent=2
        )
        + "\n"
    )
    print(json.dumps(summaries), flush=True)


if __name__ == "__main__":
    main()
