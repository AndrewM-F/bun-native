"""Find paths recorded within one bounded GC trace.

Target addresses can come from a later snapshot and may have been reused. Trace
edges are incomplete and lack VM or thread identity. Slot tracing, when present,
records candidates but does not attribute them to threads. A missing path is not
proof of absence, and even a path does not establish a production root.
"""

import argparse
import collections
import json
import struct
from pathlib import Path


def trace_paths(path, targets, scan_slots=False):
    data = path.read_bytes()
    if len(data) < 40:
        raise ValueError("Truncated trace header")
    magic, version, stride, epoch, attempted, written = struct.unpack_from(
        "<8sIIQQQ", data
    )
    if (
        (magic, version, stride) != (b"BNGCTRC1", 1, 24)
        or not epoch
        or not written
        or attempted != written
        or len(data) != 40 + written * stride
    ):
        raise ValueError("Invalid or overflowed trace")
    roots = set()
    incoming = collections.defaultdict(set)
    slots = collections.defaultdict(set)
    spans = set()
    kinds = set()
    for source, target, kind, reserved in struct.iter_unpack(
        "<QQII", memoryview(data)[40:]
    ):
        if (
            not target
            or kind not in ({1, 2, 3, 4, 5} if scan_slots else {1, 2, 3})
            or reserved
        ):
            raise ValueError("Malformed trace record")
        kinds.add(kind)
        if kind == 1:
            roots.add(target)
        elif kind in (2, 3) and source:
            incoming[target].add((source, kind))
        elif kind == 4:
            if not source:
                raise ValueError("Missing scan slot")
            slots[target].add(source)
        elif kind == 5:
            if not source or source >= target:
                raise ValueError("Invalid scanned span")
            spans.add((source, target))
    if kinds != ({1, 2, 3, 4, 5} if scan_slots else {1, 2, 3}):
        raise ValueError("Trace lacks one or more requested event kinds")
    paths = []
    for target in targets:
        queue = collections.deque([target])
        visited = {target}
        child = {}
        found = None
        while queue:
            node = queue.popleft()
            if node in roots:
                found = node
                break
            for parent, kind in sorted(incoming[node]):
                if parent not in visited:
                    visited.add(parent)
                    child[parent] = (node, kind)
                    queue.append(parent)
        path_records = None
        if found is not None:
            root = {"address": hex(found), "event": "conservative-match"}
            if scan_slots:
                root["candidateSlots"] = [
                    {
                        "slot": hex(slot),
                        "candidateSpans": [
                            [hex(start), hex(end)]
                            for start, end in sorted(spans)
                            if start <= slot < end
                        ],
                    }
                    for slot in sorted(slots[found])
                ]
            path_records = [root]
            while found != target:
                found, kind = child[found]
                path_records.append(
                    {
                        "address": hex(found),
                        "event": "hidden" if kind == 2 else "ordinary",
                    }
                )
        paths.append({"target": hex(target), "path": path_records})
    return {"file": str(path), "epoch": epoch, "records": written, "paths": paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("target", nargs="+", type=lambda value: int(value, 0))
    parser.add_argument("--scan-slots", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            trace_paths(args.trace, args.target, scan_slots=args.scan_slots), indent=2
        )
    )


if __name__ == "__main__":
    main()
