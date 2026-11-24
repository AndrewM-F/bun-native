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
    def test_strong_timer_checks_identity_and_only_changes_one_declaration(self):
        original = (
            b'extern "C" __attribute__((weak)) void WTFTimer__update(int);\n'
            b'extern "C" __attribute__((weak)) void WTFTimer__cancel();\n'
        )
        with patch.object(
            ADJUST, "TIMER_SOURCE_SHA256", hashlib.sha256(original).hexdigest()
        ):
            adjusted = ADJUST.make_timer_strong(original)
            self.assertEqual(
                adjusted,
                b'extern "C" void WTFTimer__update(int);\n'
                b'extern "C" __attribute__((weak)) void WTFTimer__cancel();\n',
            )
            with self.assertRaises(ValueError):
                ADJUST.make_timer_strong(original + b"changed")
        ambiguous = original + original
        with (
            patch.object(
                ADJUST, "TIMER_SOURCE_SHA256", hashlib.sha256(ambiguous).hexdigest()
            ),
            self.assertRaises(ValueError),
        ):
            ADJUST.make_timer_strong(ambiguous)

    def test_strong_timer_build_records_the_runtime_source_change(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = workspace / "bun-source"
            webkit = workspace / "webkit-source"
            temp = workspace / "runner-temp"
            root.mkdir()
            temp.mkdir()
            timer = webkit / "Source/WTF/wtf/bun/RunLoopBun.cpp"
            timer.parent.mkdir(parents=True)
            original = b'extern "C" __attribute__((weak)) void WTFTimer__update(int);\n'
            timer.write_bytes(original)
            icu = b'Write-Host "not $ICU_VERSION: removing it"\n'
            (webkit / "build-icu.ps1").write_bytes(icu)
            manifest = temp / "manifest.json"
            with (
                patch.object(ADJUST, "CHANGES", {}),
                patch.object(ADJUST, "ICU_SHA256", hashlib.sha256(icu).hexdigest()),
                patch.object(
                    ADJUST, "TIMER_SOURCE_SHA256", hashlib.sha256(original).hexdigest()
                ),
                patch.dict(
                    ADJUST.os.environ,
                    {
                        "GITHUB_ACTIONS": "true",
                        "GITHUB_WORKSPACE": str(workspace),
                        "RUNNER_TEMP": str(temp),
                    },
                ),
                patch.object(
                    ADJUST.sys,
                    "argv",
                    ["script", str(root), str(webkit), str(manifest), "--strong-timer"],
                ),
            ):
                ADJUST.main()
            entry = ADJUST.json.loads(manifest.read_text())[
                "webkit/Source/WTF/wtf/bun/RunLoopBun.cpp"
            ]
            self.assertEqual(
                entry["originalSha256"], hashlib.sha256(original).hexdigest()
            )
            self.assertEqual(
                entry["adjustedSha256"], hashlib.sha256(timer.read_bytes()).hexdigest()
            )
            self.assertIn(b'extern "C" void WTFTimer__update', timer.read_bytes())

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
