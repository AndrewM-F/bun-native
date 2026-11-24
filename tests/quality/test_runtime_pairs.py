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
    def test_aot_reference_override_is_explicit_and_not_inherited(self):
        inherited = {
            "CONTROL_AOT_REFERENCE_COMPILER": "unexpected",
            "CONTROL_AOT_EXPECT_JIT_PRESENT": "1",
            "KEEP": "yes",
        }
        normal = PAIRS.control_environment(inherited, "pinned")
        self.assertNotIn("CONTROL_AOT_REFERENCE_COMPILER", normal)
        self.assertNotIn("CONTROL_AOT_EXPECT_JIT_PRESENT", normal)
        diagnostic = PAIRS.control_environment(inherited, "pinned", jit_present=True)
        self.assertEqual(diagnostic["CONTROL_AOT_EXPECT_JIT_PRESENT"], "1")
        self.assertEqual(normal["KEEP"], "yes")
        self.assertEqual(normal["CONTROL_EXPECTED_REVISION"], "pinned")
        development = PAIRS.control_environment(inherited, "pinned", "distributed")
        self.assertEqual(development["CONTROL_AOT_REFERENCE_COMPILER"], "distributed")

    def test_requires_each_valid_control_in_both_execution_modes(self):
        records = [
            {
                "variant": variant,
                "valid": True,
                "records": [
                    {"mode": "development", "valid": True},
                    {"mode": "aot", "valid": True},
                ],
            }
            for variant in ("baseline", "clear", "pin")
        ]
        self.assertTrue(PAIRS.observations_valid(records))
        records[2]["valid"] = False
        self.assertFalse(PAIRS.observations_valid(records))
        records[2]["valid"] = True
        records[2]["records"][0]["valid"] = False
        self.assertFalse(PAIRS.observations_valid(records))
        records[2]["records"][0]["valid"] = True
        records[1]["records"] = [
            {"mode": "development", "valid": True},
            {"mode": "development", "valid": True},
        ]
        self.assertFalse(PAIRS.observations_valid(records))
        self.assertFalse(PAIRS.observations_valid([None, None, None]))


if __name__ == "__main__":
    unittest.main()
