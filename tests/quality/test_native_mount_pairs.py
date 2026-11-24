"""Reject incomplete or invalid native mount measurements."""

import importlib.util
import unittest
from pathlib import Path

path = Path(__file__).resolve().parents[2] / "benchmarks/renderer/native-mount-pairs.py"
spec = importlib.util.spec_from_file_location("native_mount_pairs", path)
assert spec and spec.loader
pairs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pairs)


class NativeMountPairsTests(unittest.TestCase):
    def test_requires_exact_host_runtime_and_samples(self):
        host = Path("/example/native-host")
        result = {
            "status": "passed",
            "host": str(host),
            "bunRevision": "pinned",
            "samples": {case: [1.0] * 50 for case in pairs.CASES},
        }
        self.assertEqual(
            pairs.validate(result, host, "pinned"), {case: 1.0 for case in pairs.CASES}
        )
        for invalid in (
            {**result, "status": "failed"},
            {**result, "host": "/other"},
            {**result, "bunRevision": "other"},
            {**result, "samples": {}},
            {**result, "samples": {**result["samples"], "mount-42": [1.0] * 49}},
            {
                **result,
                "samples": {**result["samples"], "mount-128": [float("nan")] * 50},
            },
        ):
            with self.assertRaises(ValueError):
                pairs.validate(invalid, host, "pinned")


if __name__ == "__main__":
    unittest.main()
