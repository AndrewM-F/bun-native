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
RENDERER_MODULE = MODULE.with_name("swap-renderer-pairs.py")
RENDERER_SPEC = importlib.util.spec_from_file_location(
    "renderer_only_pairs", RENDERER_MODULE
)
assert RENDERER_SPEC and RENDERER_SPEC.loader
renderer_pairs = importlib.util.module_from_spec(RENDERER_SPEC)
RENDERER_SPEC.loader.exec_module(renderer_pairs)


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

    def test_renderer_results_require_each_distinct_scenario(self):
        rows = [
            {"scenario": scenario, "rows": width, "samples": 2000, "p50Ms": 1.0}
            for scenario in renderer_pairs.SCENARIOS
            for width in (100, 500)
        ]
        result = {"bun": "pinned", "results": rows}
        self.assertEqual(len(renderer_pairs.validate(result, "pinned")), 10)
        for invalid in (
            {**result, "bun": "other"},
            {**result, "results": rows[:-1]},
            {**result, "results": [*rows[:-1], rows[0]]},
            {**result, "results": [{**rows[0], "p50Ms": float("nan")}, *rows[1:]]},
        ):
            with self.assertRaises(ValueError):
                renderer_pairs.validate(invalid, "pinned")


if __name__ == "__main__":
    unittest.main()
