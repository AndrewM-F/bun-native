"""Install an opt-in trace into a source-pinned, isolated Windows runtime build.

The runtime is diagnostic only. Captured events are not necessarily complete:
concurrent VMs, deferred marking and uninstrumented paths can add roots or edges.
Missing events never establish absence; overflow invalidates the trace. This does
not modify the shipped runtime.
"""

import hashlib
import json
import os
import sys
from pathlib import Path


def sha(data):
    return hashlib.sha256(data).hexdigest()


def replace_once(data, before, after):
    if data.count(before) != 1:
        raise ValueError("Expected exactly one pinned collector source marker")
    return data.replace(before, after)


def transform(roots, visitor, bindings, normal_edges=False):
    roots = replace_once(
        roots,
        b'#include "ConservativeRoots.h"\n',
        b'#include "ConservativeRoots.h"\n#include "BNCollectorTraceBuffer.h"\n'
        b'extern "C" uint64_t BNCollectorTraceBegin() { return BNTrace::begin(); }\n'
        b'extern "C" void BNCollectorTraceEnd(uint64_t epoch) { BNTrace::finish(epoch); }\n'
        b'extern "C" void BNCollectorTraceRecord(uint32_t kind, const void* source, const void* target) { BNTrace::record(kind, source, target); }\n',
    )
    roots = replace_once(
        roots,
        b"        if (isJSCellKind(cellKind))\n            markHook.markKnownJSCell(static_cast<JSCell*>(p));\n",
        b"        if (isJSCellKind(cellKind)) {\n            BNCollectorTraceRecord(1, pointer, p);\n            markHook.markKnownJSCell(static_cast<JSCell*>(p));\n        }\n",
    )
    visitor = replace_once(
        visitor,
        b"WTF_ALLOW_UNSAFE_BUFFER_USAGE_BEGIN\n",
        b'extern "C" void BNCollectorTraceRecord(uint32_t, const void*, const void*);\n\nWTF_ALLOW_UNSAFE_BUFFER_USAGE_BEGIN\n',
    )
    visitor = replace_once(
        visitor,
        b"ALWAYS_INLINE void SlotVisitor::appendHiddenUnbarriered(JSCell* cell)\n{\n",
        b"ALWAYS_INLINE void SlotVisitor::appendHiddenUnbarriered(JSCell* cell)\n{\n    if (cell) BNCollectorTraceRecord(2, m_currentCell, cell);\n",
    )
    if normal_edges:
        visitor = replace_once(
            visitor,
            b"ALWAYS_INLINE void SlotVisitor::appendUnbarriered(JSCell* cell)\n{\n",
            b"ALWAYS_INLINE void SlotVisitor::appendUnbarriered(JSCell* cell)\n{\n    if (cell) BNCollectorTraceRecord(3, m_currentCell, cell);\n",
        )
    bindings = replace_once(
        bindings,
        b"size_t JSC__VM__runGC(JSC::VM* vm, bool sync)\n{\n    JSC::JSLockHolder lock(vm);\n",
        b'extern "C" uint64_t BNCollectorTraceBegin();\nextern "C" void BNCollectorTraceEnd(uint64_t);\n\nsize_t JSC__VM__runGC(JSC::VM* vm, bool sync)\n{\n    JSC::JSLockHolder lock(vm);\n    const uint64_t bnTraceEpoch = BNCollectorTraceBegin();\n',
    )
    bindings = replace_once(
        bindings,
        b"    return vm->heap.sizeAfterLastFullCollection();\n}\n",
        b"    BNCollectorTraceEnd(bnTraceEpoch);\n    return vm->heap.sizeAfterLastFullCollection();\n}\n",
    )
    return roots, visitor, bindings


def main():
    if os.name != "nt" or os.environ.get("GITHUB_ACTIONS") != "true":
        raise ValueError(
            "Collector instrumentation requires an isolated Windows Actions checkout"
        )
    if len(sys.argv) not in (4, 5) or (
        len(sys.argv) == 5 and sys.argv[4] != "--normal-edges"
    ):
        raise ValueError("Expected bun, webkit, manifest and optional --normal-edges")
    bun, webkit, manifest = (Path(x).resolve() for x in sys.argv[1:4])
    normal_edges = len(sys.argv) == 5
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    runner_temp = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    if bun != workspace / "bun-source" or webkit != workspace / "webkit-source":
        raise ValueError("Unexpected source checkout paths")
    if manifest.parent != runner_temp:
        raise ValueError("Trace manifest must be in RUNNER_TEMP")
    paths = (
        webkit / "Source/JavaScriptCore/heap/ConservativeRoots.cpp",
        webkit / "Source/JavaScriptCore/heap/SlotVisitorInlines.h",
        bun / "src/jsc/bindings/bindings.cpp",
    )
    expected = (
        "22102e605c012f0134a35c1191f7f4ebb159836fcc8dd078103abcf5de26ff3f",
        "4d8bff93828c52d141a631f2c261a349b0c122b0aab81290262566d339ff901b",
        "691b8688cc95a88ae35832dd9b58b368914ad12c89ea8532977ea33e6226d45e",
    )
    original = tuple(path.read_bytes() for path in paths)
    if tuple(map(sha, original)) != expected:
        raise ValueError("Upstream collector sources differ from pinned revisions")
    adjusted = transform(*original, normal_edges=normal_edges)
    header = paths[0].parent / "BNCollectorTraceBuffer.h"
    if header.exists() or manifest.exists():
        raise ValueError("Trace header or manifest already exists")
    content = Path("benchmarks/retention/collector-trace-buffer.h").read_bytes()
    plan = {
        "originalSha256": list(map(sha, original)),
        "instrumentedSha256": list(map(sha, adjusted)),
        "headerSha256": sha(content),
        "eventKinds": [1, 2, 3] if normal_edges else [1, 2],
        "scope": "Opt-in diagnostic runtime; traces conservative matches and hidden visitor calls around explicit Bun.gc. Concurrent VMs and uninstrumented paths are not attributed; missing events never prove absence and overflow invalidates the trace.",
    }
    # The checkout is ephemeral; fail on any mismatch before changing any file.
    for path, data in zip(paths, adjusted, strict=True):
        path.write_bytes(data)
    header.write_bytes(content)
    manifest.write_text(json.dumps(plan, indent=2) + "\n")


if __name__ == "__main__":
    main()
