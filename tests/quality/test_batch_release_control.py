"""The paired retention build must reverse only the declared candidate."""

import hashlib
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "benchmarks/retention/batch-release-build.py"
SPEC = importlib.util.spec_from_file_location("batch_release_build", PATH)
assert SPEC and SPEC.loader
CONTROL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTROL)


class BatchReleaseControlTests(unittest.TestCase):
    def test_reconstructs_the_pinned_baseline_exactly(self):
        candidate = (ROOT / "packages/core/src/batches.ts").read_bytes()
        baseline = CONTROL.baseline_source(candidate)
        self.assertEqual(
            hashlib.sha256(baseline).hexdigest(),
            "60725d766db72490aff5008c87d012d9992a2a1a66254781b67ee9cf72493c61",
        )
        with self.assertRaises(ValueError):
            CONTROL.baseline_source(baseline)


if __name__ == "__main__":
    unittest.main()
