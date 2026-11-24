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

    def test_origin_labels_require_exact_span_match(self):
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
                    (200, 100, 6, 0),
                    (90, 210, 8, 0),
                ],
            )
            result = ANALYZE.trace_paths(trace, [3], scan_slots=True, scan_origins=True)
            span = result["paths"][0]["path"][0]["candidateSlots"][0]["candidateSpans"][
                0
            ]
            self.assertEqual(span["originEvents"], ["conducting-stack"])
            with self.assertRaises(ValueError):
                ANALYZE.trace_paths(trace, [3], scan_slots=True)

    def test_clear_bounds_are_ranges_not_retaining_edges(self):
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
                    (100, 200, 6, 0),
                    (110, 130, 9, 0),
                    (150, 158, 10, 0),
                ],
            )
            result = ANALYZE.trace_paths(
                trace, [3, 130], scan_slots=True, scan_origins=True, clear_bounds=True
            )
            slot = result["paths"][0]["path"][0]["candidateSlots"][0]
            self.assertEqual(slot["insideClearRanges"], [["0x6e", "0x82"]])
            self.assertEqual(result["frameAnchors"], [["0x96", "0x9e"]])
            self.assertIsNone(result["paths"][1]["path"])

    def test_unwind_ranges_are_metadata_and_missing_frames_are_not_inferred(self):
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
                    (100, 200, 6, 0),
                    (101, 110, 9, 0),
                    (110, 118, 10, 0),
                    (115, 130, 11, 0),
                    (115, 1000, 12, 0),
                    (115, 900, 13, 0),
                    (130, 2000, 12, 0),
                ],
            )
            result = ANALYZE.trace_paths(
                trace,
                [3, 130],
                scan_slots=True,
                scan_origins=True,
                clear_bounds=True,
                unwind=True,
            )
            slot = result["paths"][0]["path"][0]["candidateSlots"][0]
            self.assertEqual(
                slot["candidateFrames"],
                [
                    {
                        "start": "0x73",
                        "end": "0x82",
                        "pcs": ["0x3e8"],
                        "imageBases": ["0x384"],
                    }
                ],
            )
            self.assertEqual(result["unwindPcs"]["0x82"], ["0x7d0"])
            self.assertIsNone(result["paths"][1]["path"])


if __name__ == "__main__":
    unittest.main()
