"""Contract checks for the isolated core ownership diagnostic."""

import hashlib
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "core_ownership_control", ROOT / "benchmarks/retention/core-ownership-control.py"
)
CONTROL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(CONTROL)


class CoreOwnershipControlTests(unittest.TestCase):
    def test_group_control_reconstructs_pinned_baseline(self):
        candidate = (ROOT / "packages/core/src/application.ts").read_text()
        baseline = CONTROL.original_application(candidate)
        self.assertEqual(
            hashlib.sha256(baseline.encode()).hexdigest(),
            "c4169633cf81c76e0163e7eaef67585cd55781c08ce51c615a3f1beb2a4c9600",
        )
        with self.assertRaises(ValueError):
            CONTROL.original_application(baseline)

    def test_variants_preserve_checkpoints_and_pin_the_correct_target(self):
        source = (ROOT / "benchmarks/solid/direct.ts").read_text()
        baseline = CONTROL.variant_source(source, "baseline")
        clear = CONTROL.variant_source(source, "clear")
        root = CONTROL.variant_source(source, "pin-root")
        listener = CONTROL.variant_source(source, "pin-listener")
        self.assertNotIn("root = undefined!", baseline)
        self.assertIn("root = undefined!", clear)
        self.assertIn("__coreDiagnosticPin = root", root)
        self.assertIn("__coreDiagnosticPin = listener", listener)
        for text in (baseline, clear, root, listener):
            self.assertIn(
                "probes: [new WeakRef(root), new WeakRef(label), new WeakRef(listener)]",
                text,
            )
            self.assertIn("await window.batch((batch) => batch.remove(root))", text)
        with self.assertRaises(ValueError):
            CONTROL.variant_source(source, "unknown")
        with self.assertRaises(ValueError):
            CONTROL.variant_source(
                source.replace("  const listener", "  const missing"), "clear"
            )

    def test_positive_pins_must_survive_the_second_checkpoint(self):
        for mode, index in (("development", 3), ("aot", 297)):
            raw = {
                "status": "failed",
                "retentionObservation": {"stillReachable": [index]},
            }
            self.assertTrue(CONTROL.pin_valid(raw, mode, "pin-root"))
            self.assertFalse(CONTROL.pin_valid(raw, mode, "pin-listener"))
            raw["retentionObservation"]["stillReachable"] = [index + 2]
            self.assertTrue(CONTROL.pin_valid(raw, mode, "pin-listener"))
            raw["status"] = "passed"
            self.assertFalse(CONTROL.pin_valid(raw, mode, "pin-listener"))


if __name__ == "__main__":
    unittest.main()
