"""Record fixed adapter workload observations over the headless protocol peer.

This isolates the real workload and public core from GPUI; it is not a native
rendering or performance comparison. The workload's assertions are unchanged.
"""

import hashlib
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path


def inspect_collector_traces(
    directory,
    normal_edges=False,
    scan_slots=False,
    scan_origins=False,
    clear_bounds=False,
):
    if clear_bounds and not scan_origins:
        raise ValueError("Clear-bound tracing requires origin tracing")
    if scan_origins and not scan_slots:
        raise ValueError("Origin tracing requires slot tracing")
    if scan_slots and not normal_edges:
        raise ValueError("Slot tracing requires normal-edge tracing")
    expected_kinds = (
        {1, 2, 3, 4, 5} if scan_slots else {1, 2, 3} if normal_edges else {1, 2}
    )
    if clear_bounds:
        expected_kinds |= {9, 10}
    allowed_kinds = expected_kinds | ({6, 7, 8} if scan_origins else set())
    files = sorted(directory.glob("bn-gc-*.bin"))
    if not files:
        raise ValueError("Instrumented development process emitted no collector traces")
    results = []
    event_kinds = set()
    for path in files:
        with path.open("rb") as stream:
            header = stream.read(40)
        if len(header) != 40:
            raise ValueError("Truncated collector trace header")
        magic, version, stride, epoch, attempted, written = struct.unpack(
            "<8sIIQQQ", header
        )
        if (
            magic != b"BNGCTRC1"
            or version != 1
            or stride != 24
            or not epoch
            or not written
            or attempted != written
            or path.stat().st_size != 40 + written * stride
        ):
            raise ValueError("Invalid or overflowed collector trace")
        with path.open("rb") as stream:
            stream.seek(40)
            while block := stream.read(24 * 4096):
                if len(block) % 24:
                    raise ValueError("Incomplete collector trace record")
                for _, target, kind, reserved in struct.iter_unpack("<QQII", block):
                    if not target or kind not in allowed_kinds or reserved:
                        raise ValueError("Malformed collector trace record")
                    event_kinds.add(kind)
        results.append(
            {
                "file": path.name,
                "epoch": epoch,
                "records": written,
                "sha256": digest(path),
            }
        )
    if not expected_kinds.issubset(event_kinds) or (
        scan_origins and not event_kinds.intersection({6, 7, 8})
    ):
        raise ValueError("Collector trace did not exercise all requested paths")
    return results


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def inspect_stack_limits(directory, traces):
    pids = set()
    for trace in traces:
        match = re.fullmatch(r"bn-gc-(\d+)-(\d+)\.bin", trace["file"])
        if match is None:
            raise ValueError("Unexpected collector trace name")
        pids.add(int(match.group(1)))
    if len(pids) != 1:
        raise ValueError("Traces do not belong to one process")
    pid = pids.pop()
    path = directory / f"stack-limits-{pid}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    if (
        record.get("pid") != pid
        or not isinstance(record.get("threadId"), int)
        or record["threadId"] <= 0
    ):
        raise ValueError("Invalid thread identity")
    if not all(
        isinstance(record.get(key), str) and record[key].isdigit()
        for key in ("low", "high")
    ):
        raise ValueError("Invalid stack bounds")
    if not 0 < int(record["low"]) < int(record["high"]) < 2**64:
        raise ValueError("Invalid stack interval")
    return record


def resolve_runtime(command, expected_revision):
    executable = shutil.which(command)
    if not executable:
        raise ValueError(f"Bun executable not found: {command}")
    runtime = Path(executable).resolve(strict=True)
    revision = subprocess.run(
        [str(runtime), "-e", "process.stdout.write(Bun.revision)"],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    ).stdout
    if revision != expected_revision:
        raise ValueError(
            f"Bun revision mismatch: expected {expected_revision}, got {revision}"
        )
    return runtime


def narrow_scan_setting(environ):
    value = environ.get("BUN_JSC_useNarrowReferenceScan")
    if value not in (None, "0", "1"):
        raise ValueError("Invalid narrow-reference scan control")
    return value


def effective_narrow_scan(stderr):
    values = re.findall(r"(?m)^\s*useNarrowReferenceScan=(true|false)\b", stderr)
    if not values or len(set(values)) != 1:
        raise ValueError("Missing or conflicting narrow-reference option dump")
    return values[0] == "true"


def valid_report(raw, adapter, mode, trial, revision, exit_code):
    observation = raw["retentionObservation"]
    expected_kinds = (
        ["container handle", "label handle", "listener"]
        if adapter == "core"
        else ["render root", "content node", "listener"]
    )
    expected_count, mounts = (10, 2) if mode == "development" else (1000, 100)
    workload = {
        "iterations": expected_count,
        "rotations": expected_count,
        "mounts": mounts,
        "rows": 32,
        "warmup": 20,
    }
    cleanup = dict.fromkeys(
        (
            "windows",
            "nodes",
            "callbacks",
            "queuedTransactions",
            "queuedCallbacks",
            "activeCallbacks",
            "serviceRequests",
        ),
        0,
    )
    for key in ("firstReachable", "stillReachable"):
        indexes = observation[key]
        if not isinstance(indexes, list) or any(
            type(index) is not int or not 0 <= index < mounts * 3 for index in indexes
        ):
            return False
    error = raw.get("error")
    disposition = (
        exit_code == 0
        and raw["status"] == "passed"
        and not observation["stillReachable"]
    ) or (
        exit_code != 0
        and raw["status"] == "failed"
        and isinstance(error, str)
        and "Disposed view/callback targets remain observable" in error
        and bool(observation["stillReachable"])
    )
    return bool(
        raw["bunRevision"] == revision
        and raw["adapter"] == adapter
        and raw["nonce"] == f"{mode}-{trial}"
        and raw["declaredMode"] == mode
        and raw["workload"] == workload
        and raw["cleanup"] == cleanup
        and observation["collectionCheckpoints"] == 2
        and observation["probesPerMount"] == 3
        and observation["probeKinds"] == expected_kinds
        and disposition
    )


def main():
    adapter = sys.argv[1]
    if adapter not in ("core", "solid", "react"):
        raise ValueError("Unknown adapter")
    peer, module, binary, output = (Path(value).resolve() for value in sys.argv[2:6])
    trials = int(sys.argv[6])
    if not 1 <= trials <= 10:
        raise ValueError("Trial count must be in 1..10")
    revision = (
        os.environ.get("CONTROL_EXPECTED_REVISION")
        or json.loads(Path("toolchain.json").read_text())["bun"]["revision"]
    )
    runtime = resolve_runtime(sys.argv[7] if len(sys.argv) > 7 else "bun", revision)
    narrow_scan = narrow_scan_setting(os.environ)
    require_narrow_dump = os.environ.get("BUN_NATIVE_DIAG_NARROW_DUMP") == "1"
    trace_requested = os.environ.get("BN_COLLECTOR_TRACE_REQUESTED") == "1"
    normal_edges = os.environ.get("BN_COLLECTOR_TRACE_NORMAL_EDGES") == "1"
    scan_slots = os.environ.get("BN_COLLECTOR_TRACE_SCAN_SLOTS") == "1"
    scan_origins = os.environ.get("BN_COLLECTOR_TRACE_SCAN_ORIGINS") == "1"
    clear_bounds = os.environ.get("BN_COLLECTOR_TRACE_CLEAR_BOUNDS") == "1"
    stack_preload = os.environ.get("BN_COLLECTOR_TRACE_STACK_PRELOAD")
    if normal_edges and not trace_requested:
        raise ValueError("Normal-edge tracing requires collector tracing")
    if scan_slots and not normal_edges:
        raise ValueError("Slot tracing requires normal-edge tracing")
    if scan_origins and not scan_slots:
        raise ValueError("Origin tracing requires slot tracing")
    if clear_bounds and not scan_origins:
        raise ValueError("Clear-bound tracing requires origin tracing")
    if stack_preload and (
        not scan_slots
        or not Path(stack_preload).is_file()
        or not Path(stack_preload).is_absolute()
        or any(char.isspace() for char in stack_preload)
        or os.environ.get("BUN_OPTIONS")
    ):
        raise ValueError("Invalid stack preload configuration")
    output.mkdir(parents=True, exist_ok=False)
    plan = {
        "revision": revision,
        "adapter": adapter,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "sha256": {
            "peer": digest(peer),
            "module": digest(module),
            "aot": digest(binary),
            "developmentRuntime": digest(runtime),
        },
        "trialsPerMode": trials,
        "ordering": "development then AOT on even trials; reverse on odd trials",
        "scope": "Actual adapter workload and headless public-core IPC, with no GPUI or paint calibration",
        "development": "DFG disabled; 10 iterations, 10 rotations, 2 mounts, 32 rows",
        "aot": "1000 iterations, 1000 rotations, 100 mounts, 32 rows",
        "narrowReferenceScanEnv": narrow_scan,
        "requireNarrowOptionDump": require_narrow_dump,
        "collectorTraceRequested": trace_requested,
        "collectorTraceNormalEdges": normal_edges,
        "collectorTraceScanSlots": scan_slots,
        "collectorTraceScanOrigins": scan_origins,
        "collectorTraceClearBounds": clear_bounds,
        "stackPreloadSha256": digest(Path(stack_preload)) if stack_preload else None,
    }
    (output / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    results = []
    invalid = 0
    for trial in range(trials):
        modes = ("development", "aot") if trial % 2 == 0 else ("aot", "development")
        for mode in modes:
            report = output / f"{trial:02}-{mode}.json"
            env = os.environ.copy()
            env.pop("BUN_NATIVE_DIAG_NARROW_DUMP", None)
            env.pop("BN_COLLECTOR_TRACE_REQUESTED", None)
            env.pop("BN_COLLECTOR_TRACE_NORMAL_EDGES", None)
            env.pop("BN_COLLECTOR_TRACE_SCAN_SLOTS", None)
            env.pop("BN_COLLECTOR_TRACE_SCAN_ORIGINS", None)
            env.pop("BN_COLLECTOR_TRACE_CLEAR_BOUNDS", None)
            env.pop("BN_COLLECTOR_TRACE_STACK_PRELOAD", None)
            env.pop("BN_COLLECTOR_TRACE_DIR", None)
            trace_directory = output / f"{trial:02}-{mode}-collector-trace"
            if trace_requested and mode == "development":
                trace_directory.mkdir(exist_ok=False)
                env["BN_COLLECTOR_TRACE_DIR"] = str(trace_directory.resolve())
                if stack_preload:
                    env["BUN_OPTIONS"] = f"--preload={stack_preload}"
            if require_narrow_dump:
                env["BUN_JSC_dumpOptions"] = "3"
            for key in (
                "BUN_JSC_useDFGJIT",
                "BUN_NATIVE_EVIDENCE_LOG",
                "BUN_NATIVE_EVIDENCE_NONCE",
            ):
                env.pop(key, None)
            if mode == "development":
                env["BUN_JSC_useDFGJIT"] = "0"
            command = (
                [str(runtime), str(module)] if mode == "development" else [str(binary)]
            )
            count = (
                ["--iterations", "10", "--rotations", "10", "--mounts", "2"]
                if mode == "development"
                else ["--iterations", "1000", "--rotations", "1000", "--mounts", "100"]
            )
            command += [
                "--host",
                str(peer),
                "--output",
                str(report),
                "--nonce",
                f"{mode}-{trial}",
                "--mode",
                mode,
                "--rows",
                "32",
                *count,
            ]
            try:
                child = subprocess.run(
                    command,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=False,
                )
                (output / f"{trial:02}-{mode}.stdout.txt").write_text(
                    child.stdout, encoding="utf-8"
                )
                (output / f"{trial:02}-{mode}.stderr.txt").write_text(
                    child.stderr, encoding="utf-8"
                )
                raw = json.loads(report.read_text()) if report.exists() else None
                observation = raw["retentionObservation"] if raw else None
                cleanup = raw["cleanup"] if raw else None
                effective_scan = (
                    effective_narrow_scan(child.stderr) if require_narrow_dump else None
                )
                traces = (
                    inspect_collector_traces(
                        trace_directory,
                        normal_edges=normal_edges,
                        scan_slots=scan_slots,
                        scan_origins=scan_origins,
                        clear_bounds=clear_bounds,
                    )
                    if trace_requested and mode == "development"
                    else None
                )
                stack_limits = (
                    inspect_stack_limits(trace_directory, traces)
                    if stack_preload and mode == "development"
                    else None
                )
                valid = bool(
                    raw
                    and valid_report(
                        raw, adapter, mode, trial, revision, child.returncode
                    )
                    and (
                        not require_narrow_dump
                        or effective_scan == (narrow_scan != "0")
                    )
                )
                result = {
                    "trial": trial,
                    "mode": mode,
                    "exit": child.returncode,
                    "valid": valid,
                    "status": raw["status"] if raw else None,
                    "retention": observation,
                    "cleanup": cleanup,
                    "effectiveNarrowReferenceScan": effective_scan,
                    "collectorTraces": traces,
                    "threadStackLimits": stack_limits,
                }
            except (
                OSError,
                ValueError,
                KeyError,
                TypeError,
                subprocess.TimeoutExpired,
            ) as error:
                valid = False
                result = {
                    "trial": trial,
                    "mode": mode,
                    "valid": False,
                    "error": str(error),
                }
            invalid += not valid
            results.append(result)
            (output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
            print(json.dumps(result), flush=True)
    if invalid:
        raise SystemExit(
            f"{invalid} processes failed outside the retention observation or produced invalid reports"
        )


if __name__ == "__main__":
    main()
