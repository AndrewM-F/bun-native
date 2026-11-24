"""Experimental React source substitutions must be unique and bounded."""

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "react_unmount_control", ROOT / "benchmarks/retention/react-unmount-control.py"
)
CONTROL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTROL)


class ReactUnmountControlTests(unittest.TestCase):
    def test_exact_source_markers_and_deliberate_pin(self):
        mount = (ROOT / "packages/react/src/mount.ts").read_text()
        entry = (ROOT / "benchmarks/solid/react.tsx").read_text()
        candidate = CONTROL.candidate_source(mount)
        pinned = CONTROL.pin_source(entry)
        self.assertIn("diagnostic < 2", candidate)
        self.assertIn("__unmountDiagnosticPins = [view, listener]", pinned)
        safe = CONTROL.safe_fixture(entry)
        self.assertIn("setText = undefined!; setRows = undefined!;", safe)
        self.assertIn(
            "__unmountDiagnosticPins = [view, listener]", CONTROL.pin_source(safe)
        )
        self.assertEqual(CONTROL.candidate_source(mount), candidate)
        with self.assertRaises(ValueError):
            CONTROL.candidate_source(candidate)
        with self.assertRaises(ValueError):
            CONTROL.pin_source(pinned)


if __name__ == "__main__":
    unittest.main()
