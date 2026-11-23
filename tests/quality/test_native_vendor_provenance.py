"""Native evidence must fingerprint local dependency build inputs, including assets."""

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class NestedVendorInputs(unittest.TestCase):
    def test_nested_crate_build_inputs_are_included(self):
        from scripts.quality.native_harness.common import vendor_source_paths

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = [
                "native/vendor/project/Cargo.toml",
                "native/vendor/project/src/lib.rs",
                "native/vendor/project/parser/Cargo.toml",
                "native/vendor/project/parser/build.rs",
                "native/vendor/project/parser/spec.yaml",
                "native/vendor/project/parser/src/lib.rs",
                "native/vendor/project/parser/res/snippet.rs",
            ]
            for name in names:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture")
            self.assertEqual(
                {
                    path.relative_to(root).as_posix()
                    for path in vendor_source_paths(root)
                },
                set(names),
            )


@unittest.skipUnless(sys.platform == "linux", "Linux evidence source snapshots")
class NativeVendorInputs(unittest.TestCase):
    def test_all_local_dependency_compile_inputs_are_fingerprinted(self):
        expected = set()
        for package in (ROOT / "native/vendor").iterdir():
            if not package.is_dir():
                continue
            for name in ("Cargo.toml", "build.rs"):
                if (path := package / name).is_file():
                    expected.add(path)
            for directory in ("src", "res"):
                expected.update(
                    path for path in (package / directory).rglob("*") if path.is_file()
                )
            for child in package.iterdir():
                if not child.is_dir() or not (child / "Cargo.toml").is_file():
                    continue
                expected.add(child / "Cargo.toml")
                if (child / "build.rs").is_file():
                    expected.add(child / "build.rs")
                expected.update(path for path in child.glob("*.yaml") if path.is_file())
                for directory in ("src", "res"):
                    expected.update(
                        path
                        for path in (child / directory).rglob("*")
                        if path.is_file()
                    )
        self.assertIn(ROOT / "native/vendor/wgpu-hal/build.rs", expected)
        self.assertIn(
            ROOT / "native/vendor/wgpu-hal/src/gles/shaders/clear.frag", expected
        )
        from scripts.quality.native_harness import (  # Linux-only imports
            native_allocation_linux,
            native_diagnostics_linux,
        )

        for module in (native_diagnostics_linux, native_allocation_linux):
            with self.subTest(runner=module.__name__):
                snapshot = module.source_snapshot()
                missing = {
                    str(path.relative_to(ROOT)) for path in expected
                } - snapshot.keys()
                self.assertEqual(missing, set(), "missing local native compile inputs")
                for path in expected:
                    with self.subTest(path=path.relative_to(ROOT)):
                        record = snapshot[str(path.relative_to(ROOT))]
                        self.assertEqual(record["bytes"], path.stat().st_size)
                        self.assertEqual(
                            record["sha256"],
                            hashlib.sha256(path.read_bytes()).hexdigest(),
                        )


if __name__ == "__main__":
    unittest.main()
