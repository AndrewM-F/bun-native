import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "fixture_core_matrix", ROOT / "benchmarks/retention/fixture-core-matrix.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
NATIVE_SPEC = importlib.util.spec_from_file_location(
    "prepare_native_fixture", ROOT / "benchmarks/retention/prepare-native-fixture.py"
)
NATIVE = importlib.util.module_from_spec(NATIVE_SPEC)
NATIVE_SPEC.loader.exec_module(NATIVE)


class FixtureCoreMatrixTests(unittest.TestCase):
    def test_native_fixture_requires_exact_proven_sources(self):
        original = (ROOT / "benchmarks/solid/react.tsx").read_bytes()
        batch = (ROOT / "packages/core/src/batches.ts").read_bytes()
        variant = NATIVE.build_variant(original, batch)
        self.assertEqual(
            NATIVE.digest(variant),
            "a79755f09a39f6f9363ccf6937b8a2262685b5ee405e07fd4496ad4d21867195",
        )
        with self.assertRaisesRegex(ValueError, "original React fixture"):
            NATIVE.build_variant(original + b" ", batch)
        with self.assertRaisesRegex(ValueError, "batch-release candidate"):
            NATIVE.build_variant(original, batch + b" ")

    def test_runs_both_variants_and_restores_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "batch.ts"
            source.write_bytes(b"candidate")
            seen = []

            def run(command, *, check, timeout):
                seen.append((source.read_bytes(), Path(command[3]).name, command[4:6]))
                self.assertTrue(check)
                self.assertEqual(timeout, 2400)

            MODULE.run_matrix(source, b"candidate", b"baseline", root, root / "peer.exe", "bun", run)
            self.assertEqual(
                seen,
                [(b"baseline", "baseline", ["3", "listener"]),
                 (b"candidate", "candidate", ["3", "listener"])],
            )
            self.assertEqual(source.read_bytes(), b"candidate")

    def test_restores_candidate_when_control_fails_or_changes_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "batch.ts"
            for tamper in (False, True):
                source.write_bytes(b"candidate")

                def run(command, *, _tamper=tamper, **kwargs):
                    if _tamper:
                        source.write_bytes(b"unexpected")
                    else:
                        raise subprocess.CalledProcessError(1, command)

                with self.assertRaises(ValueError if tamper else subprocess.CalledProcessError):
                    MODULE.run_matrix(
                        source, b"candidate", b"baseline", root, root / "peer.exe", "bun", run
                    )
                self.assertEqual(source.read_bytes(), b"candidate")


if __name__ == "__main__":
    unittest.main()
