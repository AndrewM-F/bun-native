"""Adapt pinned upstream build scripts for a Windows diagnostic build.

This runs only in the disposable upstream checkout. The generator expands each
relative argument back to its original absolute path before sorting or reading.
It changes build/codegen scripts, not runtime source; qualification is separate.
"""

import hashlib
import json
import os
import sys
from pathlib import Path

CHANGES = {
    "scripts/build/aot.ts": (
        "ca6587d50aa58c1a31dc20528e2898525a05b33a1b7ea09c5e4553745d5c4c3a",
        (
            (
                'import { resolve } from "node:path";',
                'import { relative, resolve } from "node:path";',
            ),
            ("`${crateOf(src)}=${src}`", "`${crateOf(src)}=${relative(cfg.cwd, src)}`"),
        ),
    ),
    "src/codegen/builtins/index.ts": (
        "864da17ac07370ef067149e4b3de6fdc5597807d88ff1df3e3ed85208798fdd5",
        (
            (
                "bindgenSources: listOf(sources).sort(compareBytes),",
                'bindgenSources: listOf(sources).map(source => { const at = source.indexOf("="); return source.slice(0, at + 1) + resolve(source.slice(at + 1)); }).sort(compareBytes),',
            ),
        ),
    ),
    "scripts/build/codegen.ts": (
        "49a21a308e1d081578ab3db31242e7f8781d0c32a757febdcd56177d0812895d",
        (
            (
                "`${crates.get(src)}=${src}`",
                "`${crates.get(src)}=${relative(cfg.cwd, src)}`",
            ),
        ),
    ),
    "src/codegen/bindgen.ts": (
        "0ee01d998363b21689ad8d6f51c93e6789ecef191105a359b1c5465e2cc5d764",
        (
            (
                "  .filter(source => source.length > 0)\n  .sort();",
                '  .filter(source => source.length > 0)\n  .map(source => { const at = source.indexOf("="); return source.slice(0, at + 1) + path.resolve(source.slice(at + 1)); })\n  .sort();',
            ),
        ),
    ),
}
ICU_SHA256 = "41bd03ef64dd84f6433edca3ede6835ad9aaf416434a2b9132d56666b348f74a"
TIMER_LINK = {
    "scripts/build/bun.ts": (
        "1e12ec96773620eabda30ac1833509128d814905ee99f8bbf5c66cac4d36a8f9",
        (
            (
                "const ldflags = [...flags.ldflags, ...systemLibs(cfg)];",
                'const ldflags = [...flags.ldflags, ...(cfg.windows ? ["/INCLUDE:WTFTimer__update"] : []), ...systemLibs(cfg)];',
            ),
        ),
    ),
}


def changes_for(root, force_timer=False):
    changes = {}
    specifications = CHANGES | TIMER_LINK if force_timer else CHANGES
    for name, (expected, replacements) in specifications.items():
        path = root / name
        original = path.read_bytes()
        if hashlib.sha256(original).hexdigest() != expected:
            raise ValueError(f"Unexpected upstream source identity: {name}")
        changed = original.decode("utf-8")
        for old, new in replacements:
            if changed.count(old) != 1:
                raise ValueError(f"Expected exactly one replacement in {name}")
            changed = changed.replace(old, new)
        changes[name] = (original, changed.encode("utf-8"))
    return changes


def fix_icu_script(original):
    if hashlib.sha256(original).hexdigest() != ICU_SHA256:
        raise ValueError("Unexpected upstream WebKit ICU script identity")
    old = b"not $ICU_VERSION: removing it"
    if original.count(old) != 1:
        raise ValueError("Expected exactly one ICU PowerShell interpolation")
    return original.replace(old, b"not ${ICU_VERSION}: removing it")


def main():
    root = Path(sys.argv[1]).resolve(strict=True)
    workspace = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve(strict=True)
    runner_temp = Path(os.environ.get("RUNNER_TEMP", ".")).resolve(strict=True)
    webkit = Path(sys.argv[2]).resolve(strict=True)
    manifest = Path(sys.argv[3]).resolve()
    if os.environ.get("GITHUB_ACTIONS") != "true" or root != workspace / "bun-source":
        raise ValueError("Adjustment requires the disposable Actions source checkout")
    if webkit != workspace / "webkit-source":
        raise ValueError("Adjustment requires the disposable Actions WebKit checkout")
    if manifest.parent != runner_temp:
        raise ValueError("Manifest must be in RUNNER_TEMP")
    if manifest.exists():
        raise ValueError("Refusing to overwrite build adjustment manifest")
    if len(sys.argv) not in (4, 5) or (
        len(sys.argv) == 5 and sys.argv[4] != "--force-timer"
    ):
        raise ValueError("Unexpected diagnostic build arguments")
    changes = changes_for(root, force_timer=len(sys.argv) == 5)
    icu_path = webkit / "build-icu.ps1"
    icu_original = icu_path.read_bytes()
    icu_adjusted = fix_icu_script(icu_original)
    manifest.write_text(
        json.dumps(
            {
                name: {
                    "originalSha256": hashlib.sha256(original).hexdigest(),
                    "adjustedSha256": hashlib.sha256(adjusted).hexdigest(),
                }
                for name, (original, adjusted) in changes.items()
            }
            | {
                "webkit/build-icu.ps1": {
                    "originalSha256": hashlib.sha256(icu_original).hexdigest(),
                    "adjustedSha256": hashlib.sha256(icu_adjusted).hexdigest(),
                }
            },
            indent=2,
        )
        + "\n"
    )
    for name, (_, adjusted) in changes.items():
        (root / name).write_bytes(adjusted)
    icu_path.write_bytes(icu_adjusted)


if __name__ == "__main__":
    main()
