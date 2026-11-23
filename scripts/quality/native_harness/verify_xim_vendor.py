"""Verify the local XIM fork against its pinned upstream files."""

import hashlib
import json
from pathlib import Path

REPOSITORY = "https://github.com/zed-industries/xim-rs"
COMMIT = "16f35a2c881b815a2b6cdfd6687988e84f8447d8"
BEFORE = b'x11rb = { version = "0.13", optional = true }'
AFTER = b'x11rb = { version = "0.14", optional = true }'


def verify(package):
    package = Path(package)
    receipt = json.loads((package / "bun-native/upstream.json").read_text())
    if receipt["repository"] != REPOSITORY or receipt["commit"] != COMMIT:
        raise ValueError("unexpected XIM upstream identity")
    files = receipt["files"]
    expected = set(files) | {"bun-native/upstream.json", "bun-native/README.md"}
    actual = set()
    for path in package.rglob("*"):
        if path.is_symlink():
            raise ValueError("unexpected XIM symlink")
        if path.is_file():
            actual.add(path.relative_to(package).as_posix())
    if actual != expected:
        raise ValueError("XIM vendor inventory changed")
    for name, record in files.items():
        data = (package / name).read_bytes()
        if name == "Cargo.toml":
            if data.count(AFTER) != 1 or BEFORE in data:
                raise ValueError("unexpected XIM dependency patch")
            data = data.replace(AFTER, BEFORE)
        if (
            len(data) != record["bytes"]
            or hashlib.sha256(data).hexdigest() != record["sha256"]
        ):
            raise ValueError(f"XIM upstream source mismatch: {name}")
    return len(files)
