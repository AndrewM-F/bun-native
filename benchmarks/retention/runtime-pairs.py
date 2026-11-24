"""Compare two same-revision Bun runtimes using bounded headless controls."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def identity(path, revision):
    path = path.resolve(strict=True)
    result = subprocess.run(
        [str(path), "-e", "process.stdout.write(Bun.revision)"],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    if result.stdout != revision:
        raise ValueError(f"Unexpected Bun revision: {result.stdout}")
    return {"path": str(path), "revision": result.stdout, "sha256": sha256(path)}


def observations_valid(records):
    return (
        isinstance(records, list)
        and len(records) == 3
        and all(isinstance(item, dict) for item in records)
        and {item.get("variant") for item in records} == {"baseline", "clear", "pin"}
        and all(
            item.get("valid") is True
            and isinstance(item.get("records"), list)
            and len(item["records"]) == 2
            and all(isinstance(record, dict) for record in item["records"])
            and all(record.get("valid") is True for record in item["records"])
            and {record.get("mode") for record in item["records"]}
            == {"development", "aot"}
            for item in records
        )
    )


def control_environment(environ, revision, aot_reference=None):
    env = {**environ, "CONTROL_EXPECTED_REVISION": revision}
    env.pop("CONTROL_AOT_REFERENCE_COMPILER", None)
    if aot_reference is not None:
        env["CONTROL_AOT_REFERENCE_COMPILER"] = aot_reference
    return env


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("peer", type=Path)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--development-controls-only", action="store_true")
    parser.add_argument("--collector-trace", action="store_true")
    parser.add_argument("--collector-normal-edges", action="store_true")
    parser.add_argument("--collector-scan-slots", action="store_true")
    parser.add_argument("--collector-scan-origins", action="store_true")
    parser.add_argument("--collector-clear-bounds", action="store_true")
    parser.add_argument("--collector-unwind", action="store_true")
    parser.add_argument("--collector-stack-limits", action="store_true")
    args = parser.parse_args()
    if args.collector_trace and not args.development_controls_only:
        raise ValueError("Collector tracing is limited to the development runtime")
    if args.collector_normal_edges and not args.collector_trace:
        raise ValueError("Normal-edge tracing requires collector tracing")
    if args.collector_scan_slots and not args.collector_normal_edges:
        raise ValueError("Slot tracing requires normal-edge tracing")
    if args.collector_scan_origins and not args.collector_scan_slots:
        raise ValueError("Origin tracing requires slot tracing")
    if args.collector_clear_bounds and not args.collector_scan_origins:
        raise ValueError("Clear-bound tracing requires origin tracing")
    if args.collector_unwind and not args.collector_clear_bounds:
        raise ValueError("Unwind tracing requires clear-bound tracing")
    if args.collector_stack_limits and not args.collector_scan_slots:
        raise ValueError("Stack-bound tracing requires slot tracing")
    if args.collector_stack_limits and os.environ.get("BUN_OPTIONS"):
        raise ValueError("Unexpected inherited Bun options")
    if not 1 <= args.pairs <= 5:
        raise ValueError("pairs must be in 1..5")
    if any(name.startswith("BUN_JSC_") for name in os.environ):
        raise ValueError("Unexpected inherited JSC options")
    peer = args.peer.resolve(strict=True)
    revision = json.loads(Path("toolchain.json").read_text())["bun"]["revision"]
    runtimes = {
        "baseline": identity(args.baseline, revision),
        "candidate": identity(args.candidate, revision),
    }
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    plan = {
        "revision": revision,
        "runtimes": runtimes,
        "peerSha256": sha256(peer),
        "pairs": args.pairs,
        "order": "baseline/candidate on even pairs; candidate/baseline on odd pairs",
        "scope": (
            "Development runtime comparison only; AOT controls use the distributed compiler, not the candidate. No native input, paint or performance qualification."
            if args.development_controls_only
            else "Headless React retention controls; no native input, paint or performance qualification."
        ),
        "aotReferenceRuntime": runtimes["baseline"]
        if args.development_controls_only
        else None,
        "collectorTrace": args.collector_trace,
        "collectorNormalEdges": args.collector_normal_edges,
        "collectorScanSlots": args.collector_scan_slots,
        "collectorScanOrigins": args.collector_scan_origins,
        "collectorClearBounds": args.collector_clear_bounds,
        "collectorUnwind": args.collector_unwind,
        "collectorStackLimits": args.collector_stack_limits,
    }
    (output / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    records = []
    for trial in range(args.pairs):
        order = (
            ("baseline", "candidate") if trial % 2 == 0 else ("candidate", "baseline")
        )
        for variant in order:
            destination = output / f"{trial:02}-{variant}"
            command = [
                sys.executable,
                "benchmarks/retention/react-dispatch-control.py",
                str(peer),
                str(destination),
                "1",
                "cycle",
                runtimes[variant]["path"],
            ]
            env = control_environment(
                os.environ,
                revision,
                runtimes["baseline"]["path"]
                if args.development_controls_only
                else None,
            )
            env.pop("BN_COLLECTOR_TRACE_DIR", None)
            env.pop("BN_COLLECTOR_TRACE_REQUESTED", None)
            env.pop("BN_COLLECTOR_TRACE_NORMAL_EDGES", None)
            env.pop("BN_COLLECTOR_TRACE_SCAN_SLOTS", None)
            env.pop("BN_COLLECTOR_TRACE_SCAN_ORIGINS", None)
            env.pop("BN_COLLECTOR_TRACE_CLEAR_BOUNDS", None)
            env.pop("BN_COLLECTOR_TRACE_UNWIND", None)
            env.pop("BN_COLLECTOR_TRACE_STACK_PRELOAD", None)
            if args.collector_trace and variant == "candidate":
                env["BN_COLLECTOR_TRACE_REQUESTED"] = "1"
                if args.collector_normal_edges:
                    env["BN_COLLECTOR_TRACE_NORMAL_EDGES"] = "1"
                if args.collector_scan_slots:
                    env["BN_COLLECTOR_TRACE_SCAN_SLOTS"] = "1"
                if args.collector_scan_origins:
                    env["BN_COLLECTOR_TRACE_SCAN_ORIGINS"] = "1"
                if args.collector_clear_bounds:
                    env["BN_COLLECTOR_TRACE_CLEAR_BOUNDS"] = "1"
                if args.collector_unwind:
                    env["BN_COLLECTOR_TRACE_UNWIND"] = "1"
                if args.collector_stack_limits:
                    env["BN_COLLECTOR_TRACE_STACK_PRELOAD"] = str(
                        Path("benchmarks/retention/windows-stack-limits.ts").resolve(
                            strict=True
                        )
                    )
            record = {
                "trial": trial,
                "variant": variant,
                "comparisonScope": "development-only"
                if args.development_controls_only
                else "development-and-aot",
                "valid": False,
            }
            try:
                with (output / f"{trial:02}-{variant}.log").open("wb") as log:
                    process = subprocess.run(
                        command,
                        env=env,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        timeout=900,
                        check=False,
                    )
                record["exit"] = process.returncode
                observations = json.loads((destination / "results.json").read_text())
                record["valid"] = process.returncode == 0 and observations_valid(
                    observations
                )
                record["observations"] = observations
            except (
                OSError,
                ValueError,
                KeyError,
                TypeError,
                subprocess.TimeoutExpired,
            ) as error:
                record["error"] = str(error)
            records.append(record)
            (output / "results.json").write_text(json.dumps(records, indent=2) + "\n")
            print(
                json.dumps(
                    {
                        key: value
                        for key, value in record.items()
                        if key != "observations"
                    }
                ),
                flush=True,
            )
    if not all(record["valid"] for record in records):
        raise SystemExit(
            "At least one runtime control was invalid; all outcomes were retained"
        )


if __name__ == "__main__":
    main()
