"""Install one source-pinned, diagnostic-only libuv inlining control."""

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
        != "41a30294437a2dcb4dc0fef635aa2625afea4ae87ae12a682f46f52fa84234c0"
    ):
        raise ValueError("Unexpected pinned libuv build specification")
    marker = b'    "patches/libuv/win-poll-no-reendgame-after-close.patch",\n'
    if original.count(marker) != 1:
        raise ValueError("Expected exactly one libuv patch insertion point")
    return original.replace(
        marker, marker + b'    "patches/libuv/diagnostic-poll-noinline.patch",\n'
    )


def main():
    workspace = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve(strict=True)
    temp = Path(os.environ.get("RUNNER_TEMP", ".")).resolve(strict=True)
    root = Path(sys.argv[1]).resolve(strict=True)
    manifest = Path(sys.argv[2]).resolve()
    if os.environ.get("GITHUB_ACTIONS") != "true" or root != workspace / "bun-source":
        raise ValueError("Control requires the disposable pinned Actions checkout")
    if manifest.parent != temp or manifest.exists():
        raise ValueError("Unexpected manifest path")
    source = root / "scripts/build/deps/libuv.ts"
    original = source.read_bytes()
    updated = modify(original)
    destination = root / "patches/libuv/diagnostic-poll-noinline.patch"
    if destination.exists():
        raise ValueError("Diagnostic patch already exists")
    patch = Path("benchmarks/retention/libuv-poll-noinline.patch").read_bytes()
    if patch.count(b"__declspec(noinline)") != 1:
        raise ValueError("Unexpected noinline patch")
    manifest.write_text(
        json.dumps(
            {
                "bunLibuvSpecOriginalSha256": sha(original),
                "bunLibuvSpecAdjustedSha256": sha(updated),
                "libuvCommit": "8023581113b276e7c1aee3f82da57ca0893faab1",
                "libuvCoreOriginalSha256": "cc4b8b7637f90322bb3e3e9b7c88a4ca03841eed8f99e0f4681a29caec1437be",
                "diagnosticPatchSha256": sha(patch),
                "scope": "Diagnostic-only compiler layout control; no assertions or GC behavior changed.",
            },
            indent=2,
        )
        + "\n"
    )
    source.write_bytes(updated)
    destination.write_bytes(patch)


if __name__ == "__main__":
    main()
