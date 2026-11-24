"""Compare fixture ownership controls with original and candidate batch code.

Runs only in an isolated Windows Actions checkout. Every listener control keeps
the existing collection checkpoints and positive pins; this is not the native
benchmark or a performance comparison.
"""

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def run_matrix(source, candidate, baseline, root, peer, runtime, run=subprocess.run):
    try:
        for name, data in (("baseline", baseline), ("candidate", candidate)):
            source.write_bytes(data)
            if source.read_bytes() != data:
                raise ValueError(f"{name} source was not installed")
            run(
                [
                    sys.executable,
                    "benchmarks/retention/react-dispatch-control.py",
                    str(peer),
                    str(root / name),
                    "3",
                    "listener",
                    runtime,
                ],
                check=True,
                timeout=2400,
            )
            if source.read_bytes() != data:
                raise ValueError(f"{name} source changed during control")
    finally:
        source.write_bytes(candidate)
    if source.read_bytes() != candidate:
        raise ValueError("Candidate source was not restored")


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.name != "nt":
        raise ValueError("This control requires an isolated Windows Actions checkout")
    root = Path(sys.argv[1]).resolve(strict=True)
    runner_temp = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    if root.parent != runner_temp or not root.is_dir():
        raise ValueError("Evidence directory must be a direct child of RUNNER_TEMP")
    runtime = shutil.which("bun")
    if not runtime:
        raise ValueError("Pinned Bun is unavailable")
    peer = root / "peer.exe"
    if not peer.is_file():
        raise ValueError("Headless protocol peer is missing")

    spec = importlib.util.spec_from_file_location(
        "batch_release_control", "benchmarks/retention/batch-release-build.py"
    )
    if spec is None or spec.loader is None:
        raise ValueError("Cannot load the source reconstruction control")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    source = Path("packages/core/src/batches.ts")
    candidate = source.read_bytes()
    baseline = build.baseline_source(candidate)
    if digest(baseline) != "60725d766db72490aff5008c87d012d9992a2a1a66254781b67ee9cf72493c61":
        raise ValueError("Original batch source does not match the pinned baseline")
    plan = {
        "baselineSha256": digest(baseline),
        "candidateSha256": digest(candidate),
        "peerSha256": digest(peer.read_bytes()),
        "runtimeSha256": digest(Path(runtime).read_bytes()),
        "order": ["baseline", "candidate"],
        "trialsPerFixture": 3,
        "scope": "Headless fixture ownership controls; not native rendering or performance.",
    }
    (root / "matrix-plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    run_matrix(source, candidate, baseline, root, peer, runtime)


if __name__ == "__main__":
    main()
