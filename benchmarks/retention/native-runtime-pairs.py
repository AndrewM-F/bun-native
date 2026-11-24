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


def main():
    if os.name != "nt" or os.environ.get("GITHUB_ACTIONS") != "true":
        raise ValueError("Native control requires a disposable Windows Actions runner")
    if any(key.startswith("BUN_JSC_") for key in os.environ):
        raise ValueError("Unexpected inherited JSC options")
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
                "scope": "Actual native React development workload, 20 updates and rotations, 100 mount cycles, DFG disabled; not an AOT or full performance qualification.",
            },
            indent=2,
        )
        + "\n"
    )
    records = []
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
                "100",
                "--rows",
                "32",
            ]
            env = {**os.environ, "BUN_JSC_useDFGJIT": "0"}
            env.pop("BUN_NATIVE_EVIDENCE_LOG", None)
            env.pop("BUN_NATIVE_EVIDENCE_NONCE", None)
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
                    and data.get("workload", {}).get("mounts") == 100
                    and data.get("lifecycles", {}).get("rowsCreated") == 3200
                    and data.get("lifecycles", {}).get("rowsDisposed") == 3200
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
