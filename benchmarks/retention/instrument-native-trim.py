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


def modify_coff(original):
    if (
        sha(original)
        != "0c3456653c73da79e97ee9b3481ee0e280420ed0ed87960af3768d6af1e50052"
    ):
        raise ValueError("Unexpected pinned COFF linker")
    marker = b'  const libraryFolders = [\n    ...getFlagValues("/libpath:"),'
    if original.count(marker) != 1:
        raise ValueError("Expected exactly one COFF library search list")
    replacement = b'  const libraryFolders = [\n    ...(process.platform === "win32" ? (process.env.LIB ?? "").split(";").filter(Boolean) : []),\n    ...getFlagValues("/libpath:"),'
    return original.replace(marker, replacement)


def modify_neutral_objects(original):
    if sha(original) != "f911f5a3bd16e7fe0e1c86ec523f651483e342a103abc0f8fbcc2e20b6498619":
        raise ValueError("Unexpected pinned COFF object parser")
    marker = b"""    } else if (machine !== 0x8664 && machine !== 0xaa64) return undefined;
    return new CoffObject(fd, base, header);"""
    if original.count(marker) != 1:
        raise ValueError("Expected exactly one COFF machine guard")
    replacement = b"""    } else if (machine === 0) {
      // Neutral COFF is supported only for data sections without relocations.
      const count = header.readUInt16LE(2);
      const tableAt = 20 + header.readUInt16LE(16);
      if (count === 0 || tableAt + count * 40 > size) return undefined;
      const table = readAt(fd, base + tableAt, count * 40);
      for (let at = 0; at < table.length; at += 40) {
        if (table.readUInt16LE(at + 32) !== 0 || (table.readUInt32LE(at + 36) & 0x20000020) !== 0)
          return undefined;
      }
    } else if (machine !== 0x8664 && machine !== 0xaa64) return undefined;
    return new CoffObject(fd, base, header);"""
    return original.replace(marker, replacement)


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
    if sys.argv[3:] not in ([], ["--native-lib"], ["--native-lib", "--neutral-data"]):
        raise ValueError("Unknown trim control")
    coff_source = root / "scripts/build/trim/linker-coff.ts"
    coff_original = coff_source.read_bytes() if sys.argv[3:] else None
    coff_updated = modify_coff(coff_original) if coff_original is not None else None
    objects_source = root / "scripts/build/trim/coff-objects.ts"
    objects_original = objects_source.read_bytes() if "--neutral-data" in sys.argv[3:] else None
    objects_updated = modify_neutral_objects(objects_original) if objects_original is not None else None
    source = root / "scripts/build/config.ts"
    original = source.read_bytes()
    updated = modify(original)
    manifest.write_text(
        json.dumps(
            {
                "originalSha256": sha(original),
                "adjustedSha256": sha(updated),
                "coffOriginalSha256": sha(coff_original)
                if coff_original is not None
                else None,
                "coffAdjustedSha256": sha(coff_updated)
                if coff_updated is not None
                else None,
                "objectsOriginalSha256": sha(objects_original) if objects_original is not None else None,
                "objectsAdjustedSha256": sha(objects_updated) if objects_updated is not None else None,
                "scope": "Diagnostic native-Windows trim-link feasibility only; upstream guard is preserved in production.",
            },
            indent=2,
        )
        + "\n"
    )
    source.write_bytes(updated)
    if coff_updated is not None:
        coff_source.write_bytes(coff_updated)
    if objects_updated is not None:
        objects_source.write_bytes(objects_updated)


if __name__ == "__main__":
    main()
