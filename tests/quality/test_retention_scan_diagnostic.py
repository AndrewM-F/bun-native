"""Controls must reject invalid or ineffective narrow-scan settings."""

import importlib.util
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
