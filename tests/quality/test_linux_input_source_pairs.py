"""Failure and equivalence contracts for source-paired native input measurements."""

import copy
import importlib.util
import unittest
from pathlib import Path

PATH = (
    Path(__file__).resolve().parents[2]
    / "benchmarks/comparison/linux-input-source-pairs.py"
)
spec = importlib.util.spec_from_file_location("linux_input_source_pairs", PATH)
PAIRS = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PAIRS)


def reports():
    driver = {
        "status": "passed",
        "renderer": {
            "status": "reported-by-native-window",
            "gpu": {"device_name": "test"},
        },
        "measurements": {
            "native_paint_file_observation": {
                "command_start_to_paint_observed_ms": 4.0,
                "paint": {"complete_expected_tree_matched": True},
            }
        },
        "paint_observer_cleanup": {"reader_stopped": True, "open_descriptors": 0},
        "checks": {
            "window": "passed",
            "app_input_event": "passed",
            "app_initial_render_report": "passed",
            "app_render_report": "passed",
            "native_paint_file_observation": "passed",
            "os_close": "passed",
            "os_input": "injected-through-XTest",
        },
        "cleanup": {"forced_termination": False},
    }
    app = {
        "status": "passed",
        "declaredMode": "aot",
        "bunRevision": "b1007f1177fd402fae67387b8548cae5ae9b5707",
        "workload": {"scenario": "input-latency", "rows": 32},
        "input": {"clicks": 1},
        "cleanup": {"windows": 0, "nodes": 0},
    }
    return driver, app


class SourcePairTests(unittest.TestCase):
    def test_requires_native_input_paint_and_cleanup(self):
        driver, app = reports()
        self.assertEqual(PAIRS.validate(driver, app, 0), (4.0, {"device_name": "test"}))
        for field in (
            "window",
            "app_input_event",
            "app_initial_render_report",
            "app_render_report",
            "native_paint_file_observation",
            "os_close",
            "os_input",
        ):
            broken = copy.deepcopy(driver)
            broken["checks"][field] = "failed"
            with self.subTest(field=field), self.assertRaises(ValueError):
                PAIRS.validate(broken, app, 0)
        broken = copy.deepcopy(driver)
        broken["paint_observer_cleanup"]["open_descriptors"] = 1
        with self.assertRaises(ValueError):
            PAIRS.validate(broken, app, 0)
        broken = copy.deepcopy(app)
        broken["cleanup"]["nodes"] = 1
        with self.assertRaises(ValueError):
            PAIRS.validate(driver, broken, 0)
        with self.assertRaises(ValueError):
            PAIRS.validate(driver, app, 1)

    def test_intervals_are_deterministic_and_reject_small_samples(self):
        self.assertEqual(
            PAIRS.interval([1.0, 2.0, 3.0]), PAIRS.interval([1.0, 2.0, 3.0])
        )
        with self.assertRaises(ValueError):
            PAIRS.interval([1.0, 2.0])


if __name__ == "__main__":
    unittest.main()
