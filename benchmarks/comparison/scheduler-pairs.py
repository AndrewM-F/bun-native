import hashlib
import json
import os
import pathlib
import statistics
import subprocess
import sys
import time

revision = json.loads(pathlib.Path("toolchain.json").read_text())["bun"]["revision"]
app = pathlib.Path(sys.argv[1])
hosts = {"baseline": pathlib.Path(sys.argv[2]), "candidate": pathlib.Path(sys.argv[3])}
out = pathlib.Path(sys.argv[4])
out.mkdir()
rows = []
env = {k: v for k, v in os.environ.items() if not k.startswith("BUN_NATIVE_")}
env["BUN_NATIVE_HOST_PROFILE"] = "release"
expected_cleanup = dict.fromkeys(
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
for i in range(24):
    order = ("baseline", "candidate", "candidate", "baseline")
    if os.environ.get("PAIR_REVERSED") == "1":
        order = ("candidate", "baseline", "baseline", "candidate")
    kind = order[i % 4]
    path = out / f"launch-{i:02}.json"
    nonce = f"signal-abba-{i:02}"
    args = [
        str(app),
        "--host",
        str(hosts[kind]),
        "--output",
        str(path),
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
        "2",
    ]
    started = time.monotonic_ns()
    try:
        p = subprocess.run(
            args,
            env={**env, "BUN_NATIVE_HOST": str(hosts[kind])},
            capture_output=True,
            timeout=90,
        )
        (out / f"launch-{i:02}.stdout.txt").write_bytes(p.stdout)
        (out / f"launch-{i:02}.stderr.txt").write_bytes(p.stderr)
        r = json.loads(path.read_text()) if path.exists() else None
        if (
            p.returncode
            or not r
            or r.get("status") != "passed"
            or r.get("nonce") != nonce
            or r.get("bunRevision") != revision
            or r.get("declaredMode") != "aot"
            or r.get("cleanup") != expected_cleanup
            or r["workload"]
            != {
                "iterations": 1000,
                "rotations": 10,
                "mounts": 1,
                "rows": 2,
                "warmup": 20,
            }
            or r["phases"]["signals"]["acknowledgement"]["count"] != 1000
        ):
            raise ValueError("invalid workload or cleanup")
        a = r["phases"]["signals"]["acknowledgement"]
        row = {
            "index": i,
            "kind": kind,
            "warmup": i < 4,
            "p50": a["p50Ms"],
            "p95": a["p95Ms"],
            "p99": a["p99Ms"],
            "total": a["totalMs"],
            "wall": (time.monotonic_ns() - started) / 1e6,
            "load": os.getloadavg(),
            "exit": p.returncode,
        }
    except Exception as e:
        row = {"index": i, "kind": kind, "error": repr(e)}
    rows.append(row)
    print(json.dumps(row), flush=True)
    if "error" in row:
        break
(out / "summary.json").write_text(
    json.dumps(
        {
            "app_sha256": hashlib.sha256(app.read_bytes()).hexdigest(),
            "hosts": {
                k: hashlib.sha256(v.read_bytes()).hexdigest() for k, v in hosts.items()
            },
            "rows": rows,
        },
        indent=2,
    )
    + "\n"
)
if len(rows) != 24 or any("error" in row for row in rows):
    sys.exit(1)
for key in ("p50", "p95", "p99", "total", "wall"):
    pairs = []
    for i in range(4, 24, 2):
        x, y = rows[i : i + 2]
        d = {x["kind"]: x[key], y["kind"]: y[key]}
        pairs.append(d["candidate"] - d["baseline"])
    print(
        key,
        "median delta",
        statistics.median(pairs),
        "candidate wins",
        sum(x < 0 for x in pairs),
        flush=True,
    )
