"""Compare exact development runtimes with the unchanged native React workload."""

import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def paint_identity(report, nonce):
    identities = []
    for key in ("initialNativePaint", "finalNativePaint"):
        item = report.get(key) or {}
        paint = item.get("paint") or {}
        renderer = item.get("renderer") or {}
        if (
            paint.get("stage") != "native-paint"
            or paint.get("nonce") != nonce
            or not isinstance(paint.get("nodes"), list)
            or renderer.get("nonce") != nonce
        ):
            raise ValueError("Missing matching native paint evidence")
        stable_renderer = {
            k: v
            for k, v in renderer.items()
            if k != "nonce" and k != "time" and not k.endswith(("_ms", "Ms"))
        }
        if not stable_renderer:
            raise ValueError("Missing native renderer identity")
        identities.append({"nodes": paint["nodes"], "renderer": stable_renderer})
    if identities[0]["renderer"] != identities[1]["renderer"]:
        raise ValueError("Renderer changed within the workload")
    return identities


def build_schedule(pair_count, performance):
    schedule = []
    for pair in range(pair_count):
        order = (
            ("baseline", "candidate") if pair % 2 == 0 else ("candidate", "baseline")
        )
        schedule.extend((pair, "ab", name, name) for name in order)
        if performance and pair % 2 == 1:
            schedule.extend(
                (pair // 2, "aa", "baseline", label) for label in ("first", "second")
            )
    return schedule


def mode_settings(args):
    if args not in (
        [],
        ["--calibration"],
        ["--performance"],
        ["--aot-jit-present"],
        ["--aot-jit-present-extended"],
        ["--aot-jit-present-calibration"],
    ):
        raise ValueError("Unexpected arguments")
    aot = args in (
        ["--aot-jit-present"],
        ["--aot-jit-present-calibration"],
        ["--aot-jit-present-extended"],
    )
    calibration = args in (["--calibration"], ["--aot-jit-present-calibration"])
    performance = args == ["--performance"]
    mounts = 2 if calibration else 100
    iterations = 1000 if performance or (aot and not calibration) else 20
    return aot, calibration, performance, mounts, iterations


def main():
    if os.name != "nt" or os.environ.get("GITHUB_ACTIONS") != "true":
        raise ValueError("Native control requires a disposable Windows Actions runner")
    if any(key.startswith("BUN_JSC_") for key in os.environ):
        raise ValueError("Unexpected inherited JSC options")
    aot, calibration, performance, mounts, iterations = mode_settings(sys.argv[6:])
    pair_count = (
        12 if performance or sys.argv[6:] == ["--aot-jit-present-extended"] else 3
    )
    host, module, baseline, candidate = [
        Path(x).resolve(strict=True) for x in sys.argv[1:5]
    ]
    root = Path(sys.argv[5]).resolve()
    root.mkdir(parents=True, exist_ok=False)
    runtimes = {"baseline": baseline, "candidate": candidate}
    revision = json.loads(Path("toolchain.json").read_text())["bun"]["revision"]
    (root / "plan.json").write_text(
        json.dumps(
            {
                "hostSha256": sha(host),
                "moduleSha256": sha(module),
                "runtimeSha256": {k: sha(v) for k, v in runtimes.items()},
                "pairs": pair_count,
                "order": "alternating AB/BA; one baseline A/A pair after every two AB pairs"
                if performance
                else "alternating AB/BA",
                "scope": f"Actual native React {'JIT-present compiled-program diagnostic' if aot else 'development'} workload, {iterations} updates and rotations, {mounts} mount cycles, calibration={calibration}, DFG {'default' if performance or aot else 'disabled'}; not trimmed AOT or cross-product performance qualification.",
            },
            indent=2,
        )
        + "\n"
    )
    records = []
    expected_paint = None
    schedule = build_schedule(pair_count, performance)
    for pair, comparison, name, label in schedule:
        dest = root / f"{comparison}-{pair:02}-{label}"
        dest.mkdir()
        report = dest / "result.json"
        nonce = str(uuid.uuid4())
        command = [str(runtimes[name])]
        if not aot:
            command.append(str(module))
        command += [
            "--host",
            str(host),
            "--output",
            str(report),
            "--nonce",
            nonce,
            "--mode",
            "aot" if aot else "development",
            "--iterations",
            str(iterations),
            "--rotations",
            str(iterations),
            "--mounts",
            str(mounts),
            "--rows",
            "32",
        ]
        if calibration:
            command.append("--calibration")
        env = dict(os.environ)
        if not performance and not aot:
            env["BUN_JSC_useDFGJIT"] = "0"
        env.pop("BUN_NATIVE_EVIDENCE_LOG", None)
        env.pop("BUN_NATIVE_EVIDENCE_NONCE", None)
        if calibration:
            env["BUN_NATIVE_EVIDENCE_LOG"] = str(dest / "native.jsonl")
            env["BUN_NATIVE_EVIDENCE_NONCE"] = nonce
        record = {
            "pair": pair,
            "comparison": comparison,
            "label": label,
            "runtime": name,
            "valid": False,
        }
        try:
            with (dest / "output.log").open("wb") as log:
                result = subprocess.run(
                    command,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=600,
                    check=False,
                )
            data = json.loads(report.read_text())
            retention = data.get("retentionObservation")
            cleanup = data.get("cleanup") or {}
            if calibration:
                paint = paint_identity(data, nonce)
                if expected_paint is None:
                    expected_paint = paint
                elif paint != expected_paint:
                    raise ValueError(
                        "Native paint or renderer differs between launches"
                    )
            record.update(
                exit=result.returncode,
                status=data.get("status"),
                retention=retention,
                cleanup=cleanup,
            )
            record["valid"] = (
                data.get("nonce") == nonce
                and data.get("adapter") == "react"
                and data.get("declaredMode") == ("aot" if aot else "development")
                and data.get("bunRevision") == revision
                and str(data.get("executable", "")).lower()
                == str(runtimes[name]).lower()
                and data.get("workload", {}).get("iterations") == iterations
                and data.get("workload", {}).get("rotations") == iterations
                and data.get("workload", {}).get("mounts") == mounts
                and data.get("lifecycles", {}).get("rowsCreated") == 32 * mounts
                and data.get("lifecycles", {}).get("rowsDisposed") == 32 * mounts
                and isinstance(retention, dict)
                and isinstance(retention.get("stillReachable"), list)
                and all(
                    cleanup.get(k) == 0
                    for k in (
                        "windows",
                        "nodes",
                        "callbacks",
                        "queuedTransactions",
                        "queuedCallbacks",
                        "activeCallbacks",
                        "serviceRequests",
                    )
                )
                and (
                    (
                        result.returncode == 0
                        and data.get("status") == "passed"
                        and not retention["stillReachable"]
                    )
                    or (
                        result.returncode != 0
                        and data.get("status") == "failed"
                        and bool(retention["stillReachable"])
                        and "Disposed view/callback targets remain observable"
                        in data.get("error", "")
                    )
                )
            )
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            record["error"] = str(error)
        records.append(record)
        (root / "results.json").write_text(json.dumps(records, indent=2) + "\n")
        print(json.dumps(record), flush=True)
    if not all(r["valid"] for r in records):
        raise SystemExit(
            "At least one native workload lacked valid retention and cleanup evidence"
        )


if __name__ == "__main__":
    main()
