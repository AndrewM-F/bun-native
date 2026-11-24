"""Controls must reject invalid or ineffective narrow-scan settings."""

import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path

PATH = (
    Path(__file__).resolve().parents[2]
    / "benchmarks/retention/headless-adapter-control.py"
)
SPEC = importlib.util.spec_from_file_location("retention_scan_diagnostic", PATH)
assert SPEC and SPEC.loader
CONTROL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTROL)


class RetentionScanDiagnosticTests(unittest.TestCase):
    def test_stack_limits_are_bound_to_trace_process(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            traces = [{"file": "bn-gc-42-3.bin"}, {"file": "bn-gc-42-4.bin"}]
            limits = directory / "stack-limits-42.json"
            limits.write_text(
                json.dumps({"pid": 42, "threadId": 7, "low": "100", "high": "200"})
            )
            self.assertEqual(
                CONTROL.inspect_stack_limits(directory, traces)["threadId"], 7
            )
            for record in (
                {"pid": 43, "threadId": 7, "low": "100", "high": "200"},
                {"pid": 42, "threadId": 7, "low": "200", "high": "100"},
                {"pid": 42, "threadId": 0, "low": "100", "high": "200"},
            ):
                limits.write_text(json.dumps(record))
                with self.assertRaises(ValueError):
                    CONTROL.inspect_stack_limits(directory, traces)
            with self.assertRaises(ValueError):
                CONTROL.inspect_stack_limits(
                    directory, traces + [{"file": "bn-gc-43-4.bin"}]
                )

    def test_collector_trace_rejects_missing_overflow_and_truncation(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            with self.assertRaises(ValueError):
                CONTROL.inspect_collector_traces(directory)
            trace = directory / "bn-gc-1-1.bin"
            header = lambda attempted, written: struct.pack(
                "<8sIIQQQ", b"BNGCTRC1", 1, 24, 1, attempted, written
            )
            with self.assertRaises(ValueError):
                CONTROL.inspect_collector_traces(
                    directory, normal_edges=True, scan_slots=True
                )
            trace.write_bytes(
                header(5, 5)
                + b"".join(struct.pack("<QQII", 1, 2, kind, 0) for kind in range(1, 6))
            )
            self.assertEqual(
                CONTROL.inspect_collector_traces(
                    directory, normal_edges=True, scan_slots=True
                )[0]["records"],
                5,
            )
            with self.assertRaises(ValueError):
                CONTROL.inspect_collector_traces(directory, normal_edges=True)
            with self.assertRaises(ValueError):
                CONTROL.inspect_collector_traces(
                    directory, normal_edges=True, scan_slots=True, scan_origins=True
                )
            trace.write_bytes(
                header(6, 6)
                + b"".join(struct.pack("<QQII", 1, 2, kind, 0) for kind in range(1, 7))
            )
            self.assertEqual(
                CONTROL.inspect_collector_traces(
                    directory, normal_edges=True, scan_slots=True, scan_origins=True
                )[0]["records"],
                6,
            )
            trace.write_bytes(header(2, 1) + bytes(24))
            with self.assertRaises(ValueError):
                CONTROL.inspect_collector_traces(directory)
            trace.write_bytes(header(1, 1) + bytes(23))
            with self.assertRaises(ValueError):
                CONTROL.inspect_collector_traces(directory)
            trace.write_bytes(header(1, 1) + bytes(24))
            with self.assertRaises(ValueError):
                CONTROL.inspect_collector_traces(directory)
            trace.write_bytes(
                header(2, 2)
                + struct.pack("<QQII", 1, 2, 1, 0)
                + struct.pack("<QQII", 2, 3, 2, 0)
            )
            self.assertEqual(
                CONTROL.inspect_collector_traces(directory)[0]["records"], 2
            )
            with self.assertRaises(ValueError):
                CONTROL.inspect_collector_traces(directory, normal_edges=True)
            trace.write_bytes(
                header(3, 3)
                + struct.pack("<QQII", 1, 2, 1, 0)
                + struct.pack("<QQII", 2, 3, 2, 0)
                + struct.pack("<QQII", 3, 4, 3, 0)
            )
            self.assertEqual(
                CONTROL.inspect_collector_traces(directory, normal_edges=True)[0][
                    "records"
                ],
                3,
            )
            with self.assertRaises(ValueError):
                CONTROL.inspect_collector_traces(directory)

    def test_setting_and_effective_dump(self):
        self.assertIsNone(CONTROL.narrow_scan_setting({}))
        self.assertEqual(
            CONTROL.narrow_scan_setting({"BUN_JSC_useNarrowReferenceScan": "0"}), "0"
        )
        self.assertFalse(
            CONTROL.effective_narrow_scan(" useNarrowReferenceScan=false\n")
        )
        self.assertTrue(CONTROL.effective_narrow_scan(" useNarrowReferenceScan=true\n"))
        for value in ("", "2", "true"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                CONTROL.narrow_scan_setting({"BUN_JSC_useNarrowReferenceScan": value})
        for dump in ("", "useNarrowReferenceScan=false\nuseNarrowReferenceScan=true\n"):
            with self.subTest(dump=dump), self.assertRaises(ValueError):
                CONTROL.effective_narrow_scan(dump)


if __name__ == "__main__":
    unittest.main()
