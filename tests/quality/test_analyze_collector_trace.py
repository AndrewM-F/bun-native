"""Collector paths must use records from a single complete epoch."""

import importlib.util
import struct
import tempfile
import unittest
from pathlib import Path

PATH = (
    Path(__file__).resolve().parents[2]
    / "benchmarks/retention/analyze-collector-trace.py"
)
SPEC = importlib.util.spec_from_file_location("analyze_collector_trace", PATH)
ANALYZE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ANALYZE)


def write_trace(path, records, attempted=None):
    count = len(records)
    path.write_bytes(
        struct.pack(
            "<8sIIQQQ",
            b"BNGCTRC1",
            1,
            24,
            7,
            count if attempted is None else attempted,
            count,
        )
        + b"".join(struct.pack("<QQII", *record) for record in records)
    )


class CollectorPathTests(unittest.TestCase):
    def test_path_uses_only_recorded_edges(self):
        with tempfile.TemporaryDirectory() as temp:
            trace = Path(temp) / "trace.bin"
            write_trace(
                trace, [(100, 1, 1, 0), (1, 2, 3, 0), (2, 3, 2, 0), (0, 4, 3, 0)]
            )
            result = ANALYZE.trace_paths(trace, [3, 4])
            self.assertEqual(result["epoch"], 7)
            self.assertEqual(
                [p["event"] for p in result["paths"][0]["path"]],
                ["conservative-match", "ordinary", "hidden"],
            )
            self.assertIsNone(result["paths"][1]["path"])
            write_trace(
                trace, [(100, 1, 1, 0), (1, 2, 3, 0), (2, 3, 2, 0)], attempted=4
            )
            with self.assertRaises(ValueError):
                ANALYZE.trace_paths(trace, [3])

    def test_scan_slots_are_reported_without_becoming_graph_edges(self):
        with tempfile.TemporaryDirectory() as temp:
            trace = Path(temp) / "trace.bin"
            write_trace(
                trace,
                [
                    (100, 1, 1, 0),
                    (1, 2, 3, 0),
                    (2, 3, 2, 0),
                    (120, 1, 4, 0),
                    (100, 200, 5, 0),
                ],
            )
            result = ANALYZE.trace_paths(trace, [3, 200], scan_slots=True)
            root = result["paths"][0]["path"][0]
            self.assertEqual(
                root["candidateSlots"],
                [{"slot": "0x78", "candidateSpans": [["0x64", "0xc8"]]}],
            )
            self.assertIsNone(result["paths"][1]["path"])
            with self.assertRaises(ValueError):
                ANALYZE.trace_paths(trace, [3])


if __name__ == "__main__":
    unittest.main()
