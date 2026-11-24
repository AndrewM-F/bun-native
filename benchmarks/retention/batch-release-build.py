"""Build source-matched baseline and callback-release AOT controls on CI only."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HEADER = b"""/** A completed entry cannot run again or retain its caller's closure. */
const consumedUpdate = () => {
  throw new NativeStateError('invalid_state', 'Batch callback has already run')
}

"""


def replace_once(data, old, new):
    if data.count(old) != 1:
        raise ValueError("Expected exactly one candidate marker")
    return data.replace(old, new)


def baseline_source(data):
    data = replace_once(
        data,
        b"  update: (batch: NativeBatch) => unknown\n",
        b"  readonly update: (batch: NativeBatch) => unknown\n",
    )
    data = replace_once(data, HEADER, b"")
    return replace_once(data, b"    entry.update = consumedUpdate\n", b"")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.name != "nt":
        raise ValueError(
            "This source-switching diagnostic runs only in an isolated Windows Actions checkout"
        )
    root = Path(sys.argv[1]).resolve(strict=True)
    runner_temp = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    if root.parent != runner_temp or not root.is_dir():
        raise ValueError("Evidence directory is not a direct child of RUNNER_TEMP")
    bun = shutil.which("bun")
    if not bun:
        raise ValueError("Pinned Bun is unavailable")
    source = Path("packages/core/src/batches.ts")
    candidate = source.read_bytes()
    baseline = baseline_source(candidate)
    if (
        hashlib.sha256(baseline).hexdigest()
        != "60725d766db72490aff5008c87d012d9992a2a1a66254781b67ee9cf72493c61"
    ):
        raise ValueError("Reconstructed baseline differs from the pinned main source")
    plan = {
        "candidateSourceSha256": hashlib.sha256(candidate).hexdigest(),
        "baselineSourceSha256": hashlib.sha256(baseline).hexdigest(),
        "scope": "Same source except callback-release candidate; headless protocol peer, not native input or presentation.",
    }
    (root / "source-plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    bundle = 'import { bundleApplication } from "./scripts/native/bundle.ts"; await bundleApplication({framework:"react",entry:"benchmarks/solid/react.tsx",outdir:process.env.CONTROL_OUT,cwd:process.cwd()})'
    try:
        source.write_bytes(baseline)
        env = {**os.environ, "CONTROL_OUT": str(root / "baseline")}
        subprocess.run([bun, "-e", bundle], env=env, check=True, timeout=180)
        if source.read_bytes() != baseline:
            raise ValueError("Baseline source changed during the isolated build")
    finally:
        source.write_bytes(candidate)
    if source.read_bytes() != candidate:
        raise ValueError("Candidate source was not restored")
    env = {**os.environ, "CONTROL_OUT": str(root / "candidate")}
    subprocess.run([bun, "-e", bundle], env=env, check=True, timeout=180)
    inspect = 'import { inspectBunExecutable } from "./scripts/native/inspect.ts"; import { inspectBunRuntime } from "./scripts/native/inspect-runtime.ts"; const graph=inspectBunExecutable(process.argv[1]); const runtime=inspectBunRuntime(process.argv[1]); if (!graph.hasCompiledProgram || runtime.jit !== "unused") throw new Error("Not AOT"); console.log(JSON.stringify({graph,runtime},null,2))'
    for variant in ("baseline", "candidate"):
        module = root / variant / "application.js"
        binary = root / f"{variant}.exe"
        with (root / f"{variant}-compile.log").open("wb") as log:
            subprocess.run(
                [
                    bun,
                    "--no-install",
                    "compile",
                    "--no-script",
                    "--production",
                    "--explain=json",
                    str(module),
                    "--outfile",
                    str(binary),
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=180,
            )
        with (root / f"{variant}-inspection.json").open("wb") as log:
            subprocess.run(
                [bun, "-e", inspect, str(binary)], stdout=log, check=True, timeout=30
            )
        plan[variant] = {
            "moduleSha256": digest(module),
            "executableSha256": digest(binary),
        }
    (root / "source-plan.json").write_text(json.dumps(plan, indent=2) + "\n")


if __name__ == "__main__":
    main()
