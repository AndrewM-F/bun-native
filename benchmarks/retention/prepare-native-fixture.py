"""Install the headless-qualified fixture variant in an isolated Windows run."""

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def build_variant(original, batch):
    if digest(original) != "ce636a55012d21d54cecc89ad0664d76d3ef9fc0a83211ca27bd301d350745a1":
        raise ValueError("Unexpected original React fixture")
    if digest(batch) != "1390922840cca0cd0f562a8a7a281e2b24cf21278eb0c4ce928a464efecf1601":
        raise ValueError("Unexpected batch-release candidate")
    spec = importlib.util.spec_from_file_location(
        "react_dispatch_control", "benchmarks/retention/react-dispatch-control.py"
    )
    if spec is None or spec.loader is None:
        raise ValueError("Cannot load the fixture control")
    control = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(control)
    variant = control.listener_source(original.decode("utf-8"), "clear-view-listener").encode()
    if digest(variant) != "a79755f09a39f6f9363ccf6937b8a2262685b5ee405e07fd4496ad4d21867195":
        raise ValueError("Fixture differs from the successful headless variant")
    return variant


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.name != "nt":
        raise ValueError("This control requires an isolated Windows Actions checkout")
    root = Path(sys.argv[1]).resolve(strict=True)
    if root.parent != Path(os.environ["RUNNER_TEMP"]).resolve(strict=True):
        raise ValueError("Evidence directory must be a direct child of RUNNER_TEMP")
    source = Path("benchmarks/solid/react.tsx")
    original = source.read_bytes()
    batch = Path("packages/core/src/batches.ts").read_bytes()
    variant = build_variant(original, batch)
    (root / "original-react.tsx.txt").write_bytes(original)
    (root / "candidate-react.tsx.txt").write_bytes(variant)
    plan = {
        "originalFixtureSha256": digest(original),
        "candidateFixtureSha256": digest(variant),
        "batchCandidateSha256": digest(batch),
        "scope": "Altered fixture and batch candidate; real native diagnostic, not the original benchmark.",
    }
    (root / "native-fixture-plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    source.write_bytes(variant)
    if source.read_bytes() != variant:
        raise ValueError("The diagnostic fixture was not installed")


if __name__ == "__main__":
    main()
