"""The native renderer comparison rejects missing and invalid observations."""

import importlib.util
import unittest
from pathlib import Path

MODULE = (
    Path(__file__).resolve().parents[2] / "benchmarks/renderer/swap-native-pairs.py"
)
SPEC = importlib.util.spec_from_file_location("renderer_swap_pairs", MODULE)
assert SPEC and SPEC.loader
pairs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pairs)


class RendererSwapPairsTests(unittest.TestCase):
    def test_checks_host_runtime_and_every_sample(self):
        host = Path("/example/native-host")
        result = {
            "status": "passed",
            "host": str(host),
            "bunRevision": "pinned",
            "samples": {case: [1.0] * 100 for case in pairs.CASES},
        }
        self.assertEqual(
            pairs.validate(result, host, "pinned"), {case: 1.0 for case in pairs.CASES}
        )
        for invalid in (
            {**result, "status": "failed"},
            {**result, "host": "/other"},
            {**result, "bunRevision": "other"},
            {**result, "samples": {}},
            {**result, "samples": {**result["samples"], "swap-500": [1.0] * 99}},
            {
                **result,
                "samples": {**result["samples"], "swap-500": [float("nan")] * 100},
            },
        ):
            with self.assertRaises(ValueError):
                pairs.validate(invalid, host, "pinned")


if __name__ == "__main__":
    unittest.main()
