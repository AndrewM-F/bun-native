"""Bounded collector trace contracts; no runtime or collector claim."""

import importlib.util
import os
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "instrument_collector", ROOT / "benchmarks/retention/instrument-collector.py"
)
INSTRUMENT = importlib.util.module_from_spec(spec)
spec.loader.exec_module(INSTRUMENT)


class CollectorTraceTests(unittest.TestCase):
    def test_all_expected_collector_hooks_are_installed(self):
        roots = (
            b'#include "ConservativeRoots.h"\n'
            b"        if (isJSCellKind(cellKind))\n"
            b"            markHook.markKnownJSCell(static_cast<JSCell*>(p));\n"
        )
        visitor = (
            b"WTF_ALLOW_UNSAFE_BUFFER_USAGE_BEGIN\n"
            b"ALWAYS_INLINE void SlotVisitor::appendUnbarriered(JSCell* cell)\n{\n"
            b"ALWAYS_INLINE void SlotVisitor::appendHiddenUnbarriered(JSCell* cell)\n{\n"
        )
        bindings = (
            b"size_t JSC__VM__runGC(JSC::VM* vm, bool sync)\n{\n"
            b"    JSC::JSLockHolder lock(vm);\n"
            b"    return vm->heap.sizeAfterLastFullCollection();\n}\n"
        )
        updated_roots, updated_visitor, updated_bindings = INSTRUMENT.transform(
            roots, visitor, bindings
        )
        self.assertIn(b"BNCollectorTraceRecord(1, pointer, p)", updated_roots)
        self.assertIn(
            b"BNCollectorTraceRecord(2, m_currentCell, cell)", updated_visitor
        )
        self.assertNotIn(b"BNCollectorTraceRecord(3,", updated_visitor)
        _, normal_visitor, _ = INSTRUMENT.transform(
            roots, visitor, bindings, normal_edges=True
        )
        self.assertIn(b"BNCollectorTraceRecord(3, m_currentCell, cell)", normal_visitor)
        with self.assertRaises(ValueError):
            INSTRUMENT.transform(
                roots,
                visitor.replace(b"appendUnbarriered", b"missing"),
                bindings,
                normal_edges=True,
            )
        self.assertLess(
            updated_bindings.index(
                b"BNCollectorTraceBegin();\n", updated_bindings.index(b"lock(vm)")
            ),
            updated_bindings.index(b"BNCollectorTraceEnd(bnTraceEpoch)"),
        )
        with self.assertRaises(ValueError):
            INSTRUMENT.transform(updated_roots, visitor, bindings)

    def test_missing_source_marker_fails_closed(self):
        with self.assertRaises(ValueError):
            INSTRUMENT.transform(b"wrong", b"wrong", b"wrong")
        with self.assertRaises(ValueError):
            INSTRUMENT.replace_once(b"abcabc", b"abc", b"x")

    def test_slot_trace_only_instruments_development_scan_loops(self):
        call = b"genericAddPointer<lookForWasmCallees>(*it, markingVersion, newlyAllocatedVersion, jsGCFilter, boxedWasmCalleeFilter, markHook);"
        roots = (
            b'#include "ConservativeRoots.h"\n'
            b"TinyBloomFilter<uintptr_t> boxedWasmCalleeFilter, MarkHook& markHook)\n{\n    ASSERT(m_heap.worldIsStopped());\n"
            b"        if (isJSCellKind(cellKind))\n            markHook.markKnownJSCell(static_cast<JSCell*>(p));\n"
            + call
            + b"\nvoid ConservativeRoots::genericAddSpan(void* begin, void* end, MarkHook& markHook)\n"
            b"    RELEASE_ASSERT(isPointerAligned(end));\n"
            + call
            + b"\n"
            + call
            + b"\n"
        )
        visitor = (
            b"WTF_ALLOW_UNSAFE_BUFFER_USAGE_BEGIN\n"
            b"ALWAYS_INLINE void SlotVisitor::appendUnbarriered(JSCell* cell)\n{\n"
            b"ALWAYS_INLINE void SlotVisitor::appendHiddenUnbarriered(JSCell* cell)\n{\n"
        )
        bindings = (
            b"size_t JSC__VM__runGC(JSC::VM* vm, bool sync)\n{\n"
            b"    JSC::JSLockHolder lock(vm);\n"
            b"    return vm->heap.sizeAfterLastFullCollection();\n}\n"
        )
        adjusted, _, _ = INSTRUMENT.transform(
            roots, visitor, bindings, normal_edges=True, scan_slots=True
        )
        self.assertEqual(adjusted.count(b"markHook, it);"), 2)
        self.assertEqual(adjusted.count(call), 1)
        self.assertIn(b"BNCollectorTraceRecord(4, bnSlot, p)", adjusted)
        self.assertIn(b"BNCollectorTraceRecord(5, begin, end)", adjusted)
        with self.assertRaises(ValueError):
            INSTRUMENT.transform(roots, visitor, bindings, scan_slots=True)

    @unittest.skipIf(
        os.name == "nt" or not shutil.which("clang++"),
        "requires clang++ and POSIX environment",
    )
    def test_concurrent_buffer_records_overflow_and_resets(self):
        source = r"""
#define BN_TRACE_CAPACITY 64
#include "collector-trace-buffer.h"
#include <cassert>
#include <thread>
#include <vector>
int main(int argc, char** argv) {
 assert(argc == 2);
 unsetenv("BN_COLLECTOR_TRACE_DIR"); assert(BNTrace::begin() == 0);
 setenv("BN_COLLECTOR_TRACE_DIR", argv[1], 1);
 auto epoch = BNTrace::begin(); assert(epoch != 0); assert(BNTrace::begin() == 0);
 std::vector<std::thread> threads;
 for (int t = 0; t < 8; ++t) threads.emplace_back([t] {
  for (int i = 0; i < 20; ++i)
   BNTrace::record(1, reinterpret_cast<void*>(static_cast<uintptr_t>(t + 1)), reinterpret_cast<void*>(static_cast<uintptr_t>(i + 1)));
 });
 for (auto& t : threads) t.join();
 assert(BNTrace::finish(epoch));
 auto next = BNTrace::begin(); assert(next > epoch);
 BNTrace::record(2, reinterpret_cast<void*>(1), reinterpret_cast<void*>(2));
 assert(BNTrace::finish(next)); assert(!BNTrace::finish(next));
}
"""
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            cpp = directory / "test.cpp"
            binary = directory / "test"
            cpp.write_text(source)
            subprocess.run(
                [
                    "clang++",
                    "-std=c++20",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-pthread",
                    "-I",
                    str(ROOT / "benchmarks/retention"),
                    str(cpp),
                    "-o",
                    str(binary),
                ],
                check=True,
                timeout=60,
            )
            subprocess.run([str(binary), str(directory)], check=True, timeout=30)
            traces = sorted(directory.glob("bn-gc-*.bin"))
            self.assertEqual(len(traces), 2)
            headers = []
            for trace in traces:
                data = trace.read_bytes()
                magic, version, stride, epoch, attempted, written = struct.unpack_from(
                    "<8sIIQQQ", data
                )
                self.assertEqual((magic, version, stride), (b"BNGCTRC1", 1, 24))
                self.assertEqual(len(data), 40 + written * stride)
                headers.append((epoch, attempted, written))
            self.assertEqual(headers, [(1, 160, 64), (2, 1, 1)])


if __name__ == "__main__":
    unittest.main()
