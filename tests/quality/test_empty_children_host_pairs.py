"""Native timing evidence must retain its semantic and host identity gates."""

import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "benchmarks/empty-children-host-pairs.py"
)
SPEC = importlib.util.spec_from_file_location("empty_children_host_pairs", MODULE_PATH)
assert SPEC and SPEC.loader
pairs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pairs)


def result():
    return {
        "status": "passed",
        "nativeExitCode": 0,
        "semanticChecks": pairs.SEMANTICS,
        "execution": {"mode": "aot"},
        "nativeHost": {"sha256": "host"},
        "source": {"commit": "source"},
        "methodology": {"instrumentation": False},
        "mountBatches": {"count": 8, "samplesMs": [1.0] * 8},
    }


class EmptyChildrenHostPairsTests(unittest.TestCase):
    def test_requires_the_exact_native_host_mode_and_all_mounts(self):
        valid = result()
        self.assertEqual(pairs.check_result(valid, "aot", "host", "source"), 8)
        for invalid in (
            {**valid, "status": "failed"},
            {**valid, "nativeExitCode": 1},
            {**valid, "semanticChecks": []},
            {**valid, "nativeHost": {"sha256": "other"}},
            {**valid, "execution": {"mode": "development"}},
            {**valid, "source": {"commit": "other"}},
            {**valid, "methodology": {"instrumentation": True}},
            {**valid, "mountBatches": {"count": 8, "samplesMs": [1.0] * 7}},
            {**valid, "mountBatches": {"count": 8, "samplesMs": [float("nan")] * 8}},
        ):
            with self.assertRaises(ValueError):
                pairs.check_result(invalid, "aot", "host", "source")
