"""A runtime comparison is valid only with every mode and positive control."""

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "runtime_pairs", ROOT / "benchmarks/retention/runtime-pairs.py"
)
assert SPEC and SPEC.loader
PAIRS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PAIRS)


class RuntimePairsTests(unittest.TestCase):
    def test_requires_each_valid_control_in_both_execution_modes(self):
        records = [
            {
                "variant": variant,
                "valid": True,
                "records": [{"mode": "development"}, {"mode": "aot"}],
            }
            for variant in ("baseline", "clear", "pin")
        ]
        self.assertTrue(PAIRS.observations_valid(records))
        records[2]["valid"] = False
        self.assertFalse(PAIRS.observations_valid(records))
        records[2]["valid"] = True
        records[1]["records"] = [{"mode": "development"}, {"mode": "development"}]
        self.assertFalse(PAIRS.observations_valid(records))
        self.assertFalse(PAIRS.observations_valid([None, None, None]))


if __name__ == "__main__":
    unittest.main()
