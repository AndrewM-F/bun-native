"""Guard the ordering and native evidence used by the runtime comparison."""

import importlib.util
import unittest
from pathlib import Path

SOURCE = (
    Path(__file__).resolve().parents[2] / "benchmarks/retention/native-runtime-pairs.py"
)
SPEC = importlib.util.spec_from_file_location("native_runtime_pairs", SOURCE)
PAIRS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PAIRS)


def report(nonce="same"):
    def stage():
        return {
            "paint": {
                "stage": "native-paint",
                "nonce": nonce,
                "nodes": [{"node_id": 1}],
            },
            "renderer": {"nonce": nonce, "backend": "directx", "time_ms": 12},
        }

    return {"initialNativePaint": stage(), "finalNativePaint": stage()}


class NativeRuntimePairsTest(unittest.TestCase):
    def test_schedule_alternates_and_interleaves_independent_aa_pairs(self):
        schedule = PAIRS.build_schedule(12, True)
        self.assertEqual(len(schedule), 36)
        for pair in range(12):
            order = [x[2] for x in schedule if x[0] == pair and x[1] == "ab"]
            self.assertEqual(
                order,
                ["baseline", "candidate"]
                if pair % 2 == 0
                else ["candidate", "baseline"],
            )
        for pair in range(6):
            control = [x for x in schedule if x[0] == pair and x[1] == "aa"]
            self.assertEqual(
                [(x[2], x[3]) for x in control],
                [("baseline", "first"), ("baseline", "second")],
            )

    def test_native_paint_requires_nonce_and_stable_renderer(self):
        data = report()
        self.assertEqual(len(PAIRS.paint_identity(data, "same")), 2)
        with self.assertRaises(ValueError):
            PAIRS.paint_identity(data, "foreign")
        data["finalNativePaint"]["renderer"]["backend"] = "other"
        with self.assertRaises(ValueError):
            PAIRS.paint_identity(data, "same")


if __name__ == "__main__":
    unittest.main()
