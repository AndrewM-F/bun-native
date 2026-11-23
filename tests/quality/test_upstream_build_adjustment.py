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
    def test_forced_timer_is_opt_in_and_checks_upstream_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "bun.ts"
            source.write_bytes(b"link old flags\n")
            forced = {
                "bun.ts": (
                    hashlib.sha256(source.read_bytes()).hexdigest(),
                    (("old flags", "forced timer"),),
                )
            }
            with (
                patch.object(ADJUST, "CHANGES", {}),
                patch.object(ADJUST, "TIMER_LINK", forced),
            ):
                self.assertEqual(ADJUST.changes_for(root), {})
                self.assertEqual(
                    ADJUST.changes_for(root, force_timer=True)["bun.ts"][1],
                    b"link forced timer\n",
                )
                source.write_bytes(b"unexpected")
                with self.assertRaises(ValueError):
                    ADJUST.changes_for(root, force_timer=True)

    def test_icu_fix_requires_the_expected_file_and_unique_interpolation(self):
        original = b'Write-Host "not $ICU_VERSION: removing it"\n'
        digest = hashlib.sha256(original).hexdigest()
        with patch.object(ADJUST, "ICU_SHA256", digest):
            self.assertEqual(
                ADJUST.fix_icu_script(original),
                b'Write-Host "not ${ICU_VERSION}: removing it"\n',
            )
            with self.assertRaises(ValueError):
                ADJUST.fix_icu_script(original + b"unexpected")

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
