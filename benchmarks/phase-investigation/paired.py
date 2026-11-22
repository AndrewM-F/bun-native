"""Run alternating traced/untraced Core AOT workloads on one host.

This is an attribution diagnostic, not a benchmark acceptance gate. It keeps
all raw reports and rejects incomplete, dropped or misaligned trace records.
"""

import hashlib
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path

app, host, output = (Path(value).resolve() for value in sys.argv[1:4])
output.mkdir()
revision = json.loads(Path("toolchain.json").read_text())["bun"]["revision"]
base_env = {
    key: value for key, value in os.environ.items() if not key.startswith("BUN_NATIVE_")
}
profile = os.environ.get("PAIR_HOST_PROFILE", "release")
if profile not in ("dev", "release"):
    raise ValueError("Invalid host profile")
base_env["BUN_NATIVE_HOST_PROFILE"] = profile
wake_test = os.environ.get("PAIR_WAKE_TEST") == "1"
rows = []
for trial in range(24):
    intervention = wake_test and (False, True, True, False)[trial % 4]
    traced = wake_test or (False, True, True, False)[trial % 4]
    report_path = output / f"launch-{trial:02}.json"
    trace_path = output / f"trace-{trial:02}.json"
    nonce = f"phase-control-{trial:02}"
    env = base_env.copy()
    if traced:
        env["BUN_NATIVE_PHASE_TRACE"] = str(trace_path)
    if intervention:
        env["BUN_NATIVE_DIAGNOSTIC_RUNLOOP_WAKE"] = "1"
    args = [
        str(app),
        "--host",
        str(host),
        "--output",
        str(report_path),
        "--nonce",
        nonce,
        "--mode",
        "aot",
        "--iterations",
        "1000",
        "--rotations",
        "10",
        "--mounts",
        "1",
        "--rows",
        "32",
    ]
    try:
        proc = subprocess.run(args, env=env, capture_output=True, timeout=120)
        (output / f"launch-{trial:02}.stdout.txt").write_bytes(proc.stdout)
        (output / f"launch-{trial:02}.stderr.txt").write_bytes(proc.stderr)
        report = json.loads(report_path.read_text())
        assert (
            proc.returncode == 0
            and report["status"] == "passed"
            and report["nonce"] == nonce
        )
        assert report["bunRevision"] == revision and report["declaredMode"] == "aot"
        assert report["workload"] == {
            "iterations": 1000,
            "rotations": 10,
            "mounts": 1,
            "rows": 32,
            "warmup": 20,
        }
        assert report["cleanup"] == dict.fromkeys(
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
        samples = report["phases"]["signals"]["acknowledgement"]["samplesMs"]
        assert len(samples) == 1000
        row = {
            "trial": trial,
            "traced": traced,
            "intervention": intervention,
            "warmup": trial < 4,
            "p50Ms": statistics.median(samples),
            "selected14to20": sum(14 <= value <= 20 for value in samples),
        }
        if traced:
            trace = json.loads(trace_path.read_text())
            assert not trace["readerTracePoisoned"]
            assert all(
                trace[name] == 0
                for name in (
                    "droppedBatches",
                    "droppedFrames",
                    "droppedDrag",
                    "droppedYields",
                    "droppedCommandDispatches",
                    "droppedCommandWakes",
                    "droppedReaderEnqueues",
                )
            )
            batches = {record[0]: record for record in trace["batches"]}
            reads = {record[0]: record for record in trace["readerEnqueues"]}
            dispatches = {record[0]: record for record in trace["commandDispatches"]}
            wakes = {record[0]: record for record in trace["commandWakes"]}
            assert len(wakes) == len(trace["commandWakes"])
            assert all(
                record[3] > 0 and record[1] <= record[2] for record in wakes.values()
            )
            assert batches[3][2] == 74 and all(
                batches[index][2] == 1 for index in range(4, 1024)
            )
            assert all(
                index in reads and reads[index][3] and index in dispatches
                for index in range(24, 1024)
            )
            row["signalReadToDispatchMs"] = [
                dispatches[24 + i][2] / 1e6 for i in range(1000)
            ]
            row["signalReadToEnqueueReturnMs"] = [
                (reads[24 + i][2] - reads[24 + i][1]) / 1e6 for i in range(1000)
            ]
            row["wakesObserved"] = sum(index in wakes for index in range(24, 1024))
            row["frames"] = len(trace["frames"])
        elif trace_path.exists():
            raise ValueError("Unexpected untraced phase output")
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AssertionError,
        subprocess.TimeoutExpired,
    ) as error:
        row = {"trial": trial, "traced": traced, "error": repr(error)}
    rows.append(row)
    (output / "summary.json").write_text(
        json.dumps(
            {
                "appSha256": hashlib.sha256(app.read_bytes()).hexdigest(),
                "hostSha256": hashlib.sha256(host.read_bytes()).hexdigest(),
                "rows": rows,
            },
            indent=2,
        )
        + "\n"
    )
    print(
        json.dumps(
            {key: value for key, value in row.items() if not isinstance(value, list)}
        ),
        flush=True,
    )
    if "error" in row:
        raise SystemExit(1)
