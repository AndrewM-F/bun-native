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


def main():
    if os.name != "nt" or os.environ.get("GITHUB_ACTIONS") != "true":
        raise ValueError("Native control requires a disposable Windows Actions runner")
    if any(key.startswith("BUN_JSC_") for key in os.environ):
        raise ValueError("Unexpected inherited JSC options")
    if sys.argv[6:] not in ([], ["--calibration"]):
        raise ValueError("Unexpected arguments")
    calibration = sys.argv[6:] == ["--calibration"]
    mounts = 2 if calibration else 100
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
                "pairs": 3,
                "order": "AB/BA/AB",
                "scope": f"Actual native React development workload, 20 updates and rotations, {mounts} mount cycles, calibration={calibration}, DFG disabled; not an AOT or full performance qualification.",
            },
            indent=2,
        )
        + "\n"
    )
    records = []
    expected_paint = None
    for pair in range(3):
        for name in (
            ("baseline", "candidate") if pair % 2 == 0 else ("candidate", "baseline")
        ):
            dest = root / f"{pair:02}-{name}"
            dest.mkdir()
            report = dest / "result.json"
            nonce = str(uuid.uuid4())
            command = [
                str(runtimes[name]),
                str(module),
                "--host",
                str(host),
                "--output",
                str(report),
                "--nonce",
                nonce,
                "--mode",
                "development",
                "--iterations",
                "20",
                "--rotations",
                "20",
                "--mounts",
                str(mounts),
                "--rows",
                "32",
            ]
            if calibration:
                command.append("--calibration")
            env = {**os.environ, "BUN_JSC_useDFGJIT": "0"}
            env.pop("BUN_NATIVE_EVIDENCE_LOG", None)
            env.pop("BUN_NATIVE_EVIDENCE_NONCE", None)
            if calibration:
                env["BUN_NATIVE_EVIDENCE_LOG"] = str(dest / "native.jsonl")
                env["BUN_NATIVE_EVIDENCE_NONCE"] = nonce
            record = {"pair": pair, "runtime": name, "valid": False}
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
                    and data.get("declaredMode") == "development"
                    and data.get("bunRevision") == revision
                    and str(data.get("executable", "")).lower()
                    == str(runtimes[name]).lower()
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
