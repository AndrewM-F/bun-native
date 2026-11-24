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


def transform_machine(data):
    if b"BNCollectorTraceRecord(" in data:
        raise ValueError("Machine scanner is already instrumented")
    data = replace_once(
        data,
        b"WTF_ALLOW_UNSAFE_BUFFER_USAGE_BEGIN\n",
        b'extern "C" void BNCollectorTraceRecord(uint32_t, const void*, const void*);\n\nWTF_ALLOW_UNSAFE_BUFFER_USAGE_BEGIN\n',
    )
    for kind, call, begin, end in (
        (
            6,
            b"    conservativeRoots.add(conductingMutatorState.stackTop, conductingMutatorState.stackOrigin, jitStubRoutines, codeBlocks);\n",
            b"conductingMutatorState.stackTop",
            b"conductingMutatorState.stackOrigin",
        ),
        (
            7,
            b"        conservativeRoots.add(registersBegin, registersEnd, jitStubRoutines, codeBlocks);\n",
            b"registersBegin",
            b"registersEnd",
        ),
        (
            8,
            b"    conservativeRoots.add(buffer, static_cast<char*>(buffer) + size, jitStubRoutines, codeBlocks);\n",
            b"buffer",
            b"static_cast<char*>(buffer) + size",
        ),
    ):
        record = (
            b"    BNCollectorTraceRecord("
            + str(kind).encode()
            + b", "
            + begin
            + b", "
            + end
            + b");\n"
        )
        data = replace_once(data, call, record + call)
    return data


def transform_clear_bounds(data):
    if b"BNCollectorTraceRecord(9," in data:
        raise ValueError("Stack clear helper is already instrumented")
    marker = b"static NEVER_INLINE SUPPRESS_ASAN void clearStackBelowCaller()\n"
    data = replace_once(
        data,
        marker,
        b'extern "C" void BNCollectorTraceRecord(uint32_t, const void*, const void*);\n'
        + marker,
    )
    loop = b"    for (size_t i = 0; i < size; ++i)\n        dead[i] = 0;\n"
    data = replace_once(
        data,
        loop,
        loop
        + b"    BNCollectorTraceRecord(9, const_cast<const char*>(&dead[0]), const_cast<const char*>(&dead[size]));\n",
    )
    marker = b"    const uint64_t bnTraceEpoch = BNCollectorTraceBegin();\n"
    return replace_once(
        data,
        marker,
        marker + b"    BNCollectorTraceRecord(10, &bnTraceEpoch, &bnTraceEpoch + 1);\n",
    )


def transform(roots, visitor, bindings, normal_edges=False, scan_slots=False):
    if scan_slots and not normal_edges:
        raise ValueError("Slot tracing requires normal edges")
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
    if scan_slots:
        roots = replace_once(
            roots,
            b"TinyBloomFilter<uintptr_t> boxedWasmCalleeFilter, MarkHook& markHook)\n{\n    ASSERT(m_heap.worldIsStopped());",
            b"TinyBloomFilter<uintptr_t> boxedWasmCalleeFilter, MarkHook& markHook, const void* bnSlot)\n{\n    ASSERT(m_heap.worldIsStopped());",
        )
        roots = replace_once(
            roots,
            b"            BNCollectorTraceRecord(1, pointer, p);\n",
            b"            BNCollectorTraceRecord(1, pointer, p);\n            if (bnSlot) BNCollectorTraceRecord(4, bnSlot, p);\n",
        )
        before, span = roots.split(
            b"void ConservativeRoots::genericAddSpan(void* begin, void* end, MarkHook& markHook)\n",
            1,
        )
        marker = b"    RELEASE_ASSERT(isPointerAligned(end));\n"
        span = replace_once(
            span,
            marker,
            marker
            + b"    if (begin && end && begin != end) BNCollectorTraceRecord(5, begin, end);\n",
        )
        call = b"genericAddPointer<lookForWasmCallees>(*it, markingVersion, newlyAllocatedVersion, jsGCFilter, boxedWasmCalleeFilter, markHook);"
        if span.count(call) != 2:
            raise ValueError("Expected two development conservative scan loops")
        span = span.replace(call, call.replace(b"markHook);", b"markHook, it);"))
        roots = (
            before
            + b"void ConservativeRoots::genericAddSpan(void* begin, void* end, MarkHook& markHook)\n"
            + span
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
        len(sys.argv) == 5
        and sys.argv[4]
        not in ("--normal-edges", "--scan-slots", "--scan-origin", "--clear-range")
    ):
        raise ValueError(
            "Expected bun, webkit, manifest and a known optional trace mode"
        )
    bun, webkit, manifest = (Path(x).resolve() for x in sys.argv[1:4])
    normal_edges = len(sys.argv) == 5
    scan_slots = len(sys.argv) == 5 and sys.argv[4] in (
        "--scan-slots",
        "--scan-origin",
        "--clear-range",
    )
    scan_origin = len(sys.argv) == 5 and sys.argv[4] in (
        "--scan-origin",
        "--clear-range",
    )
    clear_range = len(sys.argv) == 5 and sys.argv[4] == "--clear-range"
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
    adjusted = transform(*original, normal_edges=normal_edges, scan_slots=scan_slots)
    if clear_range:
        adjusted = (adjusted[0], adjusted[1], transform_clear_bounds(adjusted[2]))
    declaration_path = paths[0].with_suffix(".h")
    declaration = None
    machine_path = paths[0].parent / "MachineStackMarker.cpp"
    machine = None
    if scan_origin:
        machine = machine_path.read_bytes()
        if (
            sha(machine)
            != "6964da97f8619aad952de9c76a207df5ca1e88f467c74fe7d297986b0676ed6a"
        ):
            raise ValueError("Machine stack marker differs from pinned revision")
        machine = transform_machine(machine)
    if scan_slots:
        declaration = declaration_path.read_bytes()
        if (
            sha(declaration)
            != "199fd588a3891126536dbbb11445ee972154fbaabf22057d7c16e67704cf50e9"
        ):
            raise ValueError("Conservative roots header differs from pinned revision")
        declaration = replace_once(
            declaration,
            b"TinyBloomFilter<uintptr_t> boxedWasmCalleeFilter, MarkHook&);",
            b"TinyBloomFilter<uintptr_t> boxedWasmCalleeFilter, MarkHook&, const void* = nullptr);",
        )
    header = paths[0].parent / "BNCollectorTraceBuffer.h"
    if header.exists() or manifest.exists():
        raise ValueError("Trace header or manifest already exists")
    content = Path("benchmarks/retention/collector-trace-buffer.h").read_bytes()
    plan = {
        "originalSha256": list(map(sha, original)),
        "instrumentedSha256": list(map(sha, adjusted)),
        "headerSha256": sha(content),
        "eventKinds": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        if clear_range
        else [1, 2, 3, 4, 5, 6, 7, 8]
        if scan_origin
        else [1, 2, 3, 4, 5]
        if scan_slots
        else [1, 2, 3]
        if normal_edges
        else [1, 2],
        "conservativeHeaderSha256": sha(declaration)
        if declaration is not None
        else None,
        "machineStackSha256": sha(machine) if machine is not None else None,
        "scope": "Opt-in diagnostic runtime; eventKinds lists recorded collector paths around explicit Bun.gc. Concurrent VMs and uninstrumented paths are not attributed; missing events never prove absence and overflow invalidates the trace.",
    }
    # The checkout is ephemeral; fail on any mismatch before changing any file.
    for path, data in zip(paths, adjusted, strict=True):
        path.write_bytes(data)
    if declaration is not None:
        declaration_path.write_bytes(declaration)
    if machine is not None:
        machine_path.write_bytes(machine)
    header.write_bytes(content)
    manifest.write_text(json.dumps(plan, indent=2) + "\n")


if __name__ == "__main__":
    main()
