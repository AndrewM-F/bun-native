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
    def test_missing_source_marker_fails_closed(self):
        with self.assertRaises(ValueError):
            INSTRUMENT.transform(b"wrong", b"wrong", b"wrong")
        with self.assertRaises(ValueError):
            INSTRUMENT.replace_once(b"abcabc", b"abc", b"x")

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
