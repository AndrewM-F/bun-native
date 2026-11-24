"""Alternate source-matched runtimes on a checked loopback round-trip workload."""

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if os.name != "nt" or os.environ.get("GITHUB_ACTIONS") != "true":
        raise ValueError("This diagnostic requires an isolated Windows runner")
    if any(key.startswith("BUN_JSC_") for key in os.environ):
        raise ValueError("Unexpected inherited JSC options")
    baseline, candidate = [Path(x).resolve(strict=True) for x in sys.argv[1:3]]
    root = Path(sys.argv[3]).resolve()
    root.mkdir(parents=True, exist_ok=False)
    source = Path("benchmarks/retention/poll-io-control.ts").resolve(strict=True)
    spec = importlib.util.spec_from_file_location(
        "native_pairs", "benchmarks/retention/native-runtime-pairs.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    schedule = module.build_schedule(12, True)
    revision = json.loads(Path("toolchain.json").read_text())["bun"]["revision"]
    runtimes = {"baseline": baseline, "candidate": candidate}
    (root / "plan.json").write_text(
        json.dumps(
            {
                "sourceSha256": sha(source),
                "runtimeSha256": {k: sha(v) for k, v in runtimes.items()},
                "revision": revision,
                "scope": "Sequential TCP loopback diagnostic, not native UI or presentation; 12 alternating AB/BA pairs with six interleaved A/A pairs.",
            },
            indent=2,
        )
        + "\n"
    )
    records = []
    for pair, comparison, name, label in schedule:
        dest = root / f"{comparison}-{pair:02}-{label}"
        dest.mkdir()
        report = dest / "result.json"
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
                    [str(runtimes[name]), str(source), str(report)],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=120,
                    check=False,
                )
            data = json.loads(report.read_text())
            record.update(exit=result.returncode, observation=data)
            record["valid"] = (
                result.returncode == 0
                and data.get("revision") == revision
                and str(data.get("executable", "")).lower()
                == str(runtimes[name]).lower()
                and data.get("warmup") == 1000
                and data.get("measured") == 50000
                and data.get("completed") == 51000
                and data.get("payloadBytes") == 8
                and data.get("transport") == "tcp-loopback"
                and data.get("cleanup") == "client closed and server closed"
                and data.get("elapsedMs", 0) > 0
            )
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            record["error"] = str(error)
        records.append(record)
        (root / "results.json").write_text(json.dumps(records, indent=2) + "\n")
        print(json.dumps(record), flush=True)
    if not all(row["valid"] for row in records):
        raise SystemExit(
            "At least one loopback control was invalid; all results retained"
        )


if __name__ == "__main__":
    main()
