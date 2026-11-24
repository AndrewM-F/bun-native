"""Permit a source-pinned diagnostic trim link on a disposable Windows runner."""

import hashlib
import json
import os
import sys
from pathlib import Path


def sha(data):
    return hashlib.sha256(data).hexdigest()


def modify(original):
    if (
        sha(original)
        != "250214955aa10df16dbd06a9858948e8b1fb42e201e70f90af7408a605114826"
    ):
        raise ValueError("Unexpected pinned build configuration")
    marker = (
        b'      linksWithLld({ darwin, crossTarget }) &&\n      host.os !== "windows",'
    )
    if original.count(marker) != 1:
        raise ValueError("Expected exactly one native Windows trim guard")
    return original.replace(marker, b"      linksWithLld({ darwin, crossTarget }),")


def main():
    workspace = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve(strict=True)
    temp = Path(os.environ.get("RUNNER_TEMP", ".")).resolve(strict=True)
    root = Path(sys.argv[1]).resolve(strict=True)
    manifest = Path(sys.argv[2]).resolve()
    if (
        os.name != "nt"
        or os.environ.get("GITHUB_ACTIONS") != "true"
        or root != workspace / "bun-source"
    ):
        raise ValueError(
            "Control requires the disposable pinned Windows Actions checkout"
        )
    if manifest.parent != temp or manifest.exists():
        raise ValueError("Unexpected manifest path")
    source = root / "scripts/build/config.ts"
    original = source.read_bytes()
    updated = modify(original)
    manifest.write_text(
        json.dumps(
            {
                "originalSha256": sha(original),
                "adjustedSha256": sha(updated),
                "scope": "Diagnostic native-Windows trim-link feasibility only; upstream guard is preserved in production.",
            },
            indent=2,
        )
        + "\n"
    )
    source.write_bytes(updated)


if __name__ == "__main__":
    main()
