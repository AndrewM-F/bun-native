"""Compare an unconditional ancestor walk against exact pinned source."""
import hashlib
from pathlib import Path

source = Path('native/protocol/src/tree.rs')
original = source.read_bytes()
if hashlib.sha256(original).hexdigest() != '3965647d1a316442adfddbab00663fe78eef5cfa38d62606586e6a74255dd177':
    raise ValueError('Unexpected baseline protocol source')
marker = b"        if child_id == parent_id || !child.children.is_empty() {\n            let mut ancestor = Some(parent_id);"
replacement = b"        {\n            let mut ancestor = Some(parent_id);"
if original.count(marker) != 1:
    raise ValueError('Expected exactly one ancestor guard')
changed = original.replace(marker, replacement)
if hashlib.sha256(changed).hexdigest() != '77f45759baff22d5dd33093a46d3858ba872ba137da3abd53e1aae5a7e3bc1a3':
    raise ValueError('Unexpected candidate source')
source.write_bytes(changed)
