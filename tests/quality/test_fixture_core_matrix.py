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


class FixtureCoreMatrixTests(unittest.TestCase):
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
