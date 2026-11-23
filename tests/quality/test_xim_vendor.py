"""Verify pinned XIM provenance and reject unexpected edits."""

import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.quality.native_harness import verify_xim_vendor as VENDOR

ROOT = Path(__file__).resolve().parents[2] / "native/vendor/xim-rs"


class XimVendorTests(unittest.TestCase):
    def test_original_sources_and_reviewed_manifest_patch(self):
        self.assertGreater(VENDOR.verify(ROOT), 10)

    def test_unreviewed_source_or_manifest_edits_fail(self):
        for name in ("src/x11rb.rs", "xim-ctext/src/lib.rs", "Cargo.toml"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                package = Path(temporary) / "xim-rs"
                shutil.copytree(ROOT, package)
                path = package / name
                path.write_text(path.read_text() + "\n# unexpected edit\n")
                with self.assertRaisesRegex(ValueError, "source mismatch"):
                    VENDOR.verify(package)

    def test_dependency_patch_must_be_exact(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "xim-rs"
            shutil.copytree(ROOT, package)
            manifest = package / "Cargo.toml"
            manifest.write_text(
                manifest.read_text().replace('version = "0.14"', 'version = "0.15"')
            )
            with self.assertRaisesRegex(ValueError, "dependency patch"):
                VENDOR.verify(package)

    def test_changed_patch_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "xim-rs"
            shutil.copytree(ROOT, package)
            patch = package / "bun-native/ascii-designation.patch"
            patch.write_text(patch.read_text() + "\n")
            with self.assertRaisesRegex(ValueError, "patch changed"):
                VENDOR.verify(package)

    def test_extra_file_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "xim-rs"
            shutil.copytree(ROOT, package)
            (package / "extra").write_text("unexpected")
            with self.assertRaisesRegex(ValueError, "inventory changed"):
                VENDOR.verify(package)


if __name__ == "__main__":
    unittest.main()
