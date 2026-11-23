"""The diagnostic build adjustment rejects unexpected upstream bytes."""

import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "upstream_build_adjustment",
    ROOT / "benchmarks/retention/shorten-upstream-build.py",
)
assert SPEC and SPEC.loader
ADJUST = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADJUST)


class UpstreamBuildAdjustmentTests(unittest.TestCase):
    def test_rejects_changed_or_ambiguous_inputs_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.ts"
            source.write_bytes(b"original marker\n")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            changes = {"input.ts": (digest, (("marker", "replacement"),))}
            with patch.object(ADJUST, "CHANGES", changes):
                result = ADJUST.changes_for(root)
                self.assertEqual(result["input.ts"][1], b"original replacement\n")
                self.assertEqual(source.read_bytes(), b"original marker\n")
                source.write_bytes(b"changed marker\n")
                with self.assertRaises(ValueError):
                    ADJUST.changes_for(root)
                self.assertEqual(source.read_bytes(), b"changed marker\n")
            source.write_bytes(b"marker marker\n")
            ambiguous = {
                "input.ts": (
                    hashlib.sha256(source.read_bytes()).hexdigest(),
                    (("marker", "x"),),
                )
            }
            with (
                patch.object(ADJUST, "CHANGES", ambiguous),
                self.assertRaises(ValueError),
            ):
                ADJUST.changes_for(root)
            self.assertEqual(source.read_bytes(), b"marker marker\n")


if __name__ == "__main__":
    unittest.main()
