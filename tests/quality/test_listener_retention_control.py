"""Listener controls retain the workload and require a live pinned listener."""

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "listener_retention_control",
    ROOT / "benchmarks/retention/react-dispatch-control.py",
)
assert SPEC and SPEC.loader
CONTROL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTROL)


class ListenerRetentionControlTests(unittest.TestCase):
    def test_controls_only_change_declared_lifetimes(self):
        source = (ROOT / "benchmarks/solid/react.tsx").read_text()
        baseline = CONTROL.listener_source(source, "baseline")
        self.assertIn("let listener:", baseline)
        self.assertIn(
            "listener = undefined", CONTROL.listener_source(source, "clear-listener")
        )
        self.assertIn(
            "setText = undefined", CONTROL.listener_source(source, "clear-setters")
        )
        self.assertIn(
            "__listenerDiagnosticPin", CONTROL.listener_source(source, "pin-listener")
        )
        self.assertIn(
            "view = undefined", CONTROL.listener_source(source, "clear-view-listener")
        )
        self.assertIn(
            "__listenerDiagnosticPin = view",
            CONTROL.listener_source(source, "pin-root"),
        )
        with self.assertRaises(ValueError):
            CONTROL.listener_source(source, "unknown")

    def test_positive_control_requires_last_listener_at_second_checkpoint(self):
        for mode, index in (("development", 5), ("aot", 299)):
            raw = {
                "status": "failed",
                "retentionObservation": {"stillReachable": [index]},
            }
            self.assertTrue(CONTROL.listener_pin_valid(raw, mode))
            raw["retentionObservation"]["stillReachable"] = []
            self.assertFalse(CONTROL.listener_pin_valid(raw, mode))


if __name__ == "__main__":
    unittest.main()
