"""Positive and negative controls for native startup evidence."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "startup_trace", ROOT / "scripts/quality/verify-startup-trace.py"
)
assert SPEC and SPEC.loader
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


class StartupTraceTests(unittest.TestCase):
    def test_requires_correlated_native_open_and_logger_records(self):
        identity = {"nonce": "fixture", "pid": 123}
        rows = [
            {**identity, "stage": "startup-log", "phase": "logger_installed"},
            {
                **identity,
                "stage": "startup-diagnostic",
                "source": "native",
                "phase": "open_window_enter",
                "request_id": 2,
                "window_id": 1,
            },
            {
                **identity,
                "stage": "startup-diagnostic",
                "source": "native",
                "phase": "open_window_returned",
                "request_id": 2,
                "window_id": 1,
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "native.jsonl"

            def write(records):
                path.write_text("".join(json.dumps(row) + "\n" for row in records))

            write(rows)
            VERIFY.verify(path)
            for broken in (
                rows[1:],
                rows[:-1],
                [*rows[:-1], {**rows[-1], "pid": 456}],
                [rows[0], rows[2], rows[1]],
            ):
                write(broken)
                with self.assertRaises(ValueError):
                    VERIFY.verify(path)


if __name__ == "__main__":
    unittest.main()
