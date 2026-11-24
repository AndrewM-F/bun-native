"""Compare direct-core fixture ownership variants over the headless peer.

The original collection checkpoints remain unchanged. Pins verify that the
oracle still detects deliberately live targets. This is not native evidence.
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
        raise ValueError("Expected exactly one core fixture marker")
    return source.replace(old, new)


def variant_source(source, variant):
    if variant not in ("baseline", "clear", "pin-root", "pin-listener"):
        raise ValueError("Unknown core fixture control")
    source = replace_once(
        source, "  const listener = () => {\n", "  let listener = () => {\n"
    )
    source = replace_once(
        source,
        "  const { root, label, button, list, rows } = await window.batch((batch) => {\n",
        "  let { root, label, button, list, rows } = await window.batch((batch) => {\n",
    )
    if variant.startswith("pin-"):
        target = "root" if variant == "pin-root" else "listener"
        source = replace_once(
            source,
            "  const unsubscribe = window.onClick(button, listener)\n",
            "  const unsubscribe = window.onClick(button, listener)\n"
            + f"  ;(globalThis as unknown as {{ __coreDiagnosticPin?: object }}).__coreDiagnosticPin = {target}\n",
        )
    if variant != "baseline":
        source = replace_once(
            source,
            "      rows.clear()\n",
            "      rows.clear()\n      root = undefined!; label = undefined!; button = undefined!; list = undefined!; listener = undefined!\n",
        )
    return source


def pin_valid(raw, mode, variant):
    if not variant.startswith("pin-"):
        return True
    offset = 0 if variant == "pin-root" else 2
    expected = (3 if mode == "development" else 297) + offset
    return (
        raw["status"] == "failed"
        and expected in raw["retentionObservation"]["stillReachable"]
    )


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def original_application(candidate):
    candidate = replace_once(
        candidate,
        "        try {\n          release()\n        } finally {\n          group.entries.length = 0\n        }\n",
        "        release()\n",
    )
    return replace_once(
        candidate,
        "        try {\n          for (const queued of group.entries) queued.reject(error)\n        } finally {\n          group.entries.length = 0\n        }\n",
        "        for (const queued of group.entries) queued.reject(error)\n",
    )


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.name != "nt":
        raise ValueError("This control requires an isolated Windows Actions checkout")
    peer = Path(sys.argv[1]).resolve(strict=True)
    output = Path(sys.argv[2]).resolve()
    runtime = shutil.which("bun")
    if not runtime or output.parent.parent != Path(os.environ["RUNNER_TEMP"]).resolve(
        strict=True
    ):
        raise ValueError("Missing runtime or unexpected evidence directory")
    output.mkdir(parents=False, exist_ok=False)
    fixture = Path("benchmarks/solid/direct.ts")
    original = fixture.read_text(encoding="utf-8")
    kind = sys.argv[3] if len(sys.argv) > 3 else "core-ownership"
    if kind not in ("core-ownership", "core-group"):
        raise ValueError("Unknown core control")
    variants = (
        ("baseline", "candidate", "pin-root", "pin-listener")
        if kind == "core-group"
        else ("baseline", "clear", "pin-root", "pin-listener")
    )
    generated = fixture.parent / ".retention-core-control.ts"
    plan = {
        "kind": kind,
        "sourceSha256": digest(fixture),
        "peerSha256": digest(peer),
        "runtimeSha256": digest(Path(runtime)),
        "trialsPerVariant": 5,
        "order": "alternating forward and reverse",
        "scope": "Headless diagnostic; collection checkpoints and assertions unchanged, not native rendering or performance.",
    }
    if kind == "core-group":
        candidate = Path("packages/core/src/application.ts").read_text(encoding="utf-8")
        baseline = original_application(candidate)
        expected = "c4169633cf81c76e0163e7eaef67585cd55781c08ce51c615a3f1beb2a4c9600"
        if hashlib.sha256(baseline.encode()).hexdigest() != expected:
            raise ValueError(
                "Reconstructed application baseline does not match pinned source"
            )
        for name, data in (("baseline", baseline), ("candidate", candidate)):
            path = output / f"{name}-application.ts.txt"
            path.write_text(data, encoding="utf-8", newline="\n")
            plan[f"{name}ApplicationSha256"] = digest(path)
    (output / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    for variant in variants:
        source = (
            original
            if kind == "core-group" and variant in ("baseline", "candidate")
            else variant_source(original, variant)
        )
        (output / f"{variant}-source.ts.txt").write_text(
            source, encoding="utf-8", newline="\n"
        )
        created = False
        try:
            with generated.open("x", encoding="utf-8", newline="\n") as file:
                created = True
                file.write(source)
            env = {
                **os.environ,
                "CONTROL_ENTRY": str(generated.resolve()),
                "CONTROL_OUT": str(output / variant),
            }
            build = 'import { bundleApplication } from "./scripts/native/bundle.ts"; await bundleApplication({framework:"solid",entry:process.env.CONTROL_ENTRY,outdir:process.env.CONTROL_OUT,cwd:process.cwd()})'
            if kind == "core-group":
                app = "baseline" if variant == "baseline" else "candidate"
                env["CONTROL_APPLICATION"] = str(output / f"{app}-application.ts.txt")
                build = 'import { bundleApplication } from "./scripts/native/bundle.ts"; let hits=0; const plugins=[{name:"group-control",setup(b){b.onLoad({filter:/application\\.ts$/},async ({path})=>{if(!path.replaceAll("\\\\","/").endsWith("/packages/core/src/application.ts")) return; hits++; return {contents:await Bun.file(process.env.CONTROL_APPLICATION).text(),loader:"ts"}})}}]; await bundleApplication({framework:"solid",entry:process.env.CONTROL_ENTRY,outdir:process.env.CONTROL_OUT,cwd:process.cwd(),plugins}); if(hits!==1) throw new Error(`Expected one application source, got ${hits}`)'
            subprocess.run([runtime, "-e", build], env=env, check=True, timeout=180)
        finally:
            if created:
                generated.unlink()
        binary = output / f"{variant}-aot.exe"
        with (output / f"{variant}-compile.log").open("wb") as log:
            subprocess.run(
                [
                    runtime,
                    "--no-install",
                    "compile",
                    "--no-script",
                    "--production",
                    "--explain=json",
                    str(output / variant / "application.js"),
                    "--outfile",
                    str(binary),
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=180,
            )
        inspect = 'import { inspectBunExecutable } from "./scripts/native/inspect.ts"; import { inspectBunRuntime } from "./scripts/native/inspect-runtime.ts"; const g=inspectBunExecutable(process.argv[1]); const r=inspectBunRuntime(process.argv[1]); if (!g.hasCompiledProgram || r.jit !== "unused") throw new Error("Not AOT"); console.log(JSON.stringify({g,r}))'
        with (output / f"{variant}-inspection.json").open("wb") as log:
            subprocess.run(
                [runtime, "-e", inspect, str(binary)],
                stdout=log,
                check=True,
                timeout=30,
            )
    records = []
    for trial in range(5):
        for variant in variants if trial % 2 == 0 else tuple(reversed(variants)):
            dest = output / f"{trial:02}-{variant}"
            args = [
                sys.executable,
                "benchmarks/retention/headless-adapter-control.py",
                "core",
                str(peer),
                str(output / variant / "application.js"),
                str(output / f"{variant}-aot.exe"),
                str(dest),
                "1",
                runtime,
            ]
            child = subprocess.run(
                args, capture_output=True, text=True, timeout=300, check=False
            )
            (output / f"{trial:02}-{variant}.stdout.txt").write_text(
                child.stdout, encoding="utf-8"
            )
            (output / f"{trial:02}-{variant}.stderr.txt").write_text(
                child.stderr, encoding="utf-8"
            )
            summary = dest / "results.json"
            observations = json.loads(summary.read_text()) if summary.exists() else []
            valid = (
                child.returncode == 0
                and len(observations) == 2
                and [x["mode"] for x in observations] == ["development", "aot"]
                and all(x["valid"] for x in observations)
            )
            if valid and variant.startswith("pin-"):
                valid = all(
                    pin_valid(
                        json.loads((dest / f"00-{x['mode']}.json").read_text()),
                        x["mode"],
                        variant,
                    )
                    for x in observations
                )
            records.append(
                {
                    "trial": trial,
                    "variant": variant,
                    "valid": valid,
                    "observations": observations,
                }
            )
            (output / "results.json").write_text(json.dumps(records, indent=2) + "\n")
            print(json.dumps(records[-1]), flush=True)
    if not all(x["valid"] for x in records):
        raise SystemExit("One or more controls are invalid")


if __name__ == "__main__":
    main()
