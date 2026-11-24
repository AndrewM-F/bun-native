"""Apply only the previously measured nonleaf control to exact pinned source."""
import hashlib
from pathlib import Path

source = Path('native/protocol/src/tree.rs')
original = source.read_bytes()
if hashlib.sha256(original).hexdigest() != '3965647d1a316442adfddbab00663fe78eef5cfa38d62606586e6a74255dd177':
    raise ValueError('Unexpected baseline protocol source')
marker = b'''        // A leaf cannot be an ancestor of another node in the valid tree.
        if child_id == parent_id || !child.children.is_empty() {
            let mut ancestor = Some(parent_id);
'''
replacement = b'''        if child_id == parent_id {
            return Err(error(
                ErrorCode::InvalidState,
                "insert would create a cycle",
            ));
        }
        // A leaf cannot be an ancestor of another node in the valid tree.
        // The parent was already checked, so start with its own parent.
        if !child.children.is_empty() {
            let mut ancestor = parent.parent;
'''
if original.count(marker) != 1:
    raise ValueError('Expected exactly one ancestor guard')
changed = original.replace(marker, replacement)
if hashlib.sha256(changed).hexdigest() != 'c6a20d84b6e665b071dc52e0d3bbe67da1f8bbdebe792b5234786bad8ee4c6a6':
    raise ValueError('Unexpected candidate source')
source.write_bytes(changed)
