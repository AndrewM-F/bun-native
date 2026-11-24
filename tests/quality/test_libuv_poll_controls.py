"""Verify diagnostic source edits fail closed before expensive runtime builds."""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


POLL = load("poll_control", "benchmarks/retention/instrument-libuv-poll.py")
TRIM = load("trim_control", "benchmarks/retention/instrument-native-trim.py")


class SourceGuardTest(unittest.TestCase):
    def test_poll_control_requires_pinned_source_and_one_insertion(self):
        marker = b'    "patches/libuv/win-poll-no-reendgame-after-close.patch",\n'
        with self.assertRaises(ValueError):
            POLL.modify(marker)
        with patch.object(
            POLL,
            "sha",
            return_value="41a30294437a2dcb4dc0fef635aa2625afea4ae87ae12a682f46f52fa84234c0",
        ):
            self.assertIn(b"diagnostic-poll-noinline.patch", POLL.modify(marker))
            self.assertIn(b"diagnostic-poll-clear.patch", POLL.modify(marker, "clear"))
            for invalid in (b"missing", marker + marker):
                with self.assertRaises(ValueError):
                    POLL.modify(invalid)
            with self.assertRaises(ValueError):
                POLL.modify(marker, "unknown")

    def test_native_trim_control_requires_the_exact_guard(self):
        guard = b'      linksWithLld({ darwin, crossTarget }) &&\n      host.os !== "windows",'
        with self.assertRaises(ValueError):
            TRIM.modify(guard)
        with patch.object(
            TRIM,
            "sha",
            return_value="250214955aa10df16dbd06a9858948e8b1fb42e201e70f90af7408a605114826",
        ):
            self.assertNotIn(b'host.os !== "windows"', TRIM.modify(guard))
            for invalid in (b"missing", guard + guard):
                with self.assertRaises(ValueError):
                    TRIM.modify(invalid)

    def test_neutral_data_control_requires_exact_source(self):
        marker = b"    } else if (machine !== 0x8664 && machine !== 0xaa64) return undefined;\n    return new CoffObject(fd, base, header);"
        with self.assertRaises(ValueError):
            TRIM.modify_neutral_objects(marker)
        with patch.object(TRIM, "sha", return_value="f911f5a3bd16e7fe0e1c86ec523f651483e342a103abc0f8fbcc2e20b6498619"):
            changed = TRIM.modify_neutral_objects(marker)
            self.assertIn(b"0x20000020", changed)
            self.assertIn(b"readUInt16LE(at + 32) !== 0", changed)
            for invalid in (b"missing", marker + marker):
                with self.assertRaises(ValueError):
                    TRIM.modify_neutral_objects(invalid)

    def test_native_coff_search_addition_requires_exact_source(self):
        marker = b'  const libraryFolders = [\n    ...getFlagValues("/libpath:"),'
        with self.assertRaises(ValueError):
            TRIM.modify_coff(marker)
        with patch.object(
            TRIM,
            "sha",
            return_value="0c3456653c73da79e97ee9b3481ee0e280420ed0ed87960af3768d6af1e50052",
        ):
            self.assertIn(b"process.env.LIB", TRIM.modify_coff(marker))
            for invalid in (b"missing", marker + marker):
                with self.assertRaises(ValueError):
                    TRIM.modify_coff(invalid)


if __name__ == "__main__":
    unittest.main()
