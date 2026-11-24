"""Compare an experimental extra React unmount commit with pins, on isolated Windows CI.

This source-substitution diagnostic keeps the original collection checkpoints.
Two empty commits may affect other React roots; this is not a production fix.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError("Expected exactly one source marker")
    return source.replace(old, new)


def candidate_source(source):
    marker = "            if (this.failure) throw this.failure\n"
    extra = (
        "            if (this.failure) throw this.failure\n"
        "            for (let diagnostic = 0; diagnostic < 2; diagnostic++) {\n"
        "              reconciler.updateContainerSync(null, this.fiber, null)\n"
        "              reconciler.flushSyncWork()\n"
        "              reconciler.flushPassiveEffects()\n"
        "              if (this.failure) throw this.failure\n"
        "            }\n"
    )
    return replace_once(source, marker, extra)


def pin_source(source):
    if "__unmountDiagnosticPins" in source:
        raise ValueError("Fixture is already instrumented")
    marker = "  await view.ready\n"
    return replace_once(
        source,
        marker,
        marker + "  ;(globalThis as any).__unmountDiagnosticPins = [view, listener]\n",
    )


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if os.name != "nt" or os.environ.get("GITHUB_ACTIONS") != "true":
        raise ValueError(
            "Only an isolated Windows Actions checkout may run this diagnostic"
        )
    peer = Path(sys.argv[1]).resolve(strict=True)
    output = Path(sys.argv[2]).resolve()
    if output.parent != Path(os.environ["RUNNER_TEMP"]).resolve(strict=True):
        raise ValueError("Evidence directory must be a direct child of RUNNER_TEMP")
    runtime = shutil.which("bun")
    if not runtime:
        raise ValueError("Missing pinned Bun")
    output.mkdir(exist_ok=False)
    original_mount = Path("packages/react/src/mount.ts").read_text(encoding="utf8")
    original_entry = Path("benchmarks/solid/react.tsx").read_text(encoding="utf8")
    variants = ("baseline", "candidate", "baseline-pin", "candidate-pin")
    sources = {
        "baseline-mount": original_mount,
        "candidate-mount": candidate_source(original_mount),
        "entry": original_entry,
        "pin-entry": pin_source(original_entry),
    }
    for name, text in sources.items():
        (output / f"{name}.ts.txt").write_text(text, encoding="utf8", newline="\n")
    plan = {
        "variants": variants,
        "pairs": 5,
        "order": "forward then reverse on alternating pairs",
        "peerSha256": digest(peer),
        "runtimeSha256": digest(Path(runtime)),
        "sources": {name: digest(output / f"{name}.ts.txt") for name in sources},
        "scope": "Headless only; two extra React commits are experimental and are not native or performance qualification.",
    }
    (output / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    bundle = r"""import { bundleApplication } from "./scripts/native/bundle.ts";
let mounts=0, entries=0;
const plugin={name:"diagnostic-control",setup(build){
 build.onLoad({filter:/[\\/]mount\.ts$/},async ({path})=>{if(!path.replaceAll("\\","/").endsWith("/packages/react/src/mount.ts")) return; mounts++; return {contents:await Bun.file(process.env.CONTROL_MOUNT).text(),loader:"ts"}});
 build.onLoad({filter:/[\\/]react\.tsx$/},async ({path})=>{if(!path.replaceAll("\\","/").endsWith("/benchmarks/solid/react.tsx")) return; entries++; return {contents:await Bun.file(process.env.CONTROL_ENTRY).text(),loader:"tsx"}});
}};
await bundleApplication({framework:"react",entry:"benchmarks/solid/react.tsx",outdir:process.env.CONTROL_OUT,cwd:process.cwd(),plugins:[plugin]});
if(mounts!==1||entries!==1)throw new Error(`unexpected substitutions ${mounts} ${entries}`);"""
    inspect = 'import { inspectBunExecutable } from "./scripts/native/inspect.ts"; import { inspectBunRuntime } from "./scripts/native/inspect-runtime.ts"; const g=inspectBunExecutable(process.argv[1]), r=inspectBunRuntime(process.argv[1]); if(!g.hasCompiledProgram||r.jit!=="unused") throw new Error("Not AOT"); console.log(JSON.stringify({g,r}));'
    for variant in variants:
        mount = (
            "candidate-mount" if variant.startswith("candidate") else "baseline-mount"
        )
        entry = "pin-entry" if variant.endswith("-pin") else "entry"
        env = {
            **os.environ,
            "CONTROL_MOUNT": str(output / f"{mount}.ts.txt"),
            "CONTROL_ENTRY": str(output / f"{entry}.ts.txt"),
            "CONTROL_OUT": str(output / variant),
        }
        subprocess.run([runtime, "-e", bundle], env=env, check=True, timeout=180)
        module = output / variant / "application.js"
        binary = output / f"{variant}.exe"
        with (output / f"{variant}-compile.log").open("wb") as log:
            subprocess.run(
                [
                    runtime,
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
        with (output / f"{variant}-inspection.json").open("wb") as log:
            subprocess.run(
                [runtime, "-e", inspect, str(binary)],
                stdout=log,
                check=True,
                timeout=30,
            )
        plan[variant] = {
            "moduleSha256": digest(module),
            "executableSha256": digest(binary),
        }
    (output / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    records = []
    for trial in range(5):
        order = variants if trial % 2 == 0 else tuple(reversed(variants))
        for variant in order:
            dest = output / f"{trial:02}-{variant}"
            command = [
                sys.executable,
                "benchmarks/retention/headless-adapter-control.py",
                "react",
                str(peer),
                str(output / variant / "application.js"),
                str(output / f"{variant}.exe"),
                str(dest),
                "1",
                runtime,
            ]
            with (output / f"{trial:02}-{variant}.log").open("wb") as log:
                child = subprocess.run(
                    command,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=600,
                    check=False,
                )
            rec = {
                "trial": trial,
                "variant": variant,
                "exit": child.returncode,
                "valid": False,
            }
            try:
                rows = json.loads((dest / "results.json").read_text())
                rec["valid"] = (
                    child.returncode == 0
                    and len(rows) == 2
                    and all(x["valid"] for x in rows)
                )
                rec["records"] = rows
                if rec["valid"] and variant.endswith("-pin"):
                    for row in rows:
                        raw = json.loads((dest / f"00-{row['mode']}.json").read_text())
                        first = 3 if row["mode"] == "development" else 297
                        if not {first, first + 2}.issubset(
                            set(raw["retentionObservation"]["stillReachable"])
                        ):
                            rec["valid"] = False
            except (OSError, ValueError, KeyError, TypeError):
                pass
            records.append(rec)
            (output / "results.json").write_text(json.dumps(records, indent=2) + "\n")
    if len(records) != 20 or not all(r["valid"] for r in records):
        raise ValueError("One or more controls were invalid; raw results retained")


if __name__ == "__main__":
    main()
