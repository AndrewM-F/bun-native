"""Listener controls retain the workload and require a live pinned listener."""

import importlib.util
import subprocess
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

    def test_cached_disposal_controls_preserve_both_positive_pins(self):
        source = (ROOT / "benchmarks/solid/react.tsx").read_text()
        baseline = CONTROL.listener_source(source, "safe-baseline")
        cleared = CONTROL.listener_source(source, "safe-clear")
        self.assertIn("if (!disposal) disposal =", baseline)
        self.assertNotIn("listener = undefined; view = undefined!;", baseline)
        self.assertIn("listener = undefined; view = undefined!;", cleared)
        for variant, target in (
            ("safe-pin-listener", "listener"),
            ("safe-pin-root", "view"),
        ):
            pinned = CONTROL.listener_source(source, variant)
            self.assertIn(f"__listenerDiagnosticPin = {target}", pinned)
            self.assertIn("listener = undefined; view = undefined!;", pinned)

    def test_cached_disposal_is_repeatable_and_preserves_failures(self):
        source = (ROOT / "benchmarks/solid/react.tsx").read_text()
        generated = CONTROL.listener_source(source, "safe-clear")
        method = next(line.strip() for line in generated.splitlines() if line.strip().startswith("dispose()"))
        method = method.removesuffix(",").replace("view = undefined!;", "view = undefined;")
        script = """
const assert = require('node:assert/strict');
async function check(fail) {
  let calls = 0, listener = () => {}, disposal, disposedMutations;
  const original = { diagnostics: { mutations: { set: 2 } },
    dispose() { calls++; return fail ? Promise.reject(new Error('failed')) : Promise.resolve(); } };
  let view = original;
  const fixture = { METHOD };
  const first = fixture.dispose(), second = fixture.dispose();
  assert.equal(first, second);
  if (fail) {
    await assert.rejects(first, /failed/);
    assert.equal(view, original);
    assert.equal(typeof listener, 'function');
  } else {
    await first;
    assert.equal(view, undefined);
    assert.equal(listener, undefined);
    assert.deepEqual(disposedMutations, { set: 2 });
  }
  assert.equal(fixture.dispose(), first);
  assert.equal(calls, 1);
}
check(false).then(() => check(true)).catch(error => { console.error(error); process.exitCode = 1; });
""".replace("METHOD", method)
        subprocess.run(["node", "-e", script], check=True, timeout=10)

    def test_shutdown_pin_must_remain_observable_at_all_three_checkpoints(self):
        for mode, index in (("development", 3), ("aot", 297)):
            raw = {
                "status": "failed",
                "retentionObservation": {"stillReachable": [index]},
                "beforeShutdownDiagnostic": [index],
                "afterShutdownDiagnostic": [index],
            }
            self.assertTrue(CONTROL.shutdown_record_valid(raw, mode, True))
            for checkpoint in ("beforeShutdownDiagnostic", "afterShutdownDiagnostic"):
                broken = {**raw, checkpoint: []}
                self.assertFalse(CONTROL.shutdown_record_valid(broken, mode, True))
            raw["retentionObservation"] = {"stillReachable": []}
            self.assertFalse(CONTROL.shutdown_record_valid(raw, mode, True))

    def test_first_observation_control_preserves_second_collection_and_assertion(self):
        source = (ROOT / "benchmarks/solid/workload.ts").read_text()
        baseline = CONTROL.first_observation_workload(source, False)
        omitted = CONTROL.first_observation_workload(source, True)
        self.assertEqual(baseline, source)
        self.assertIn("const firstReachable: number[] = []", omitted)
        self.assertIn("const stillReachable = probes.flatMap", omitted)
        self.assertIn("if (stillReachable.length > 0)", omitted)
        self.assertEqual(omitted.count("Bun.gc(true)"), source.count("Bun.gc(true)"))


if __name__ == "__main__":
    unittest.main()
