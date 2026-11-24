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


def trace_paths(
    path, targets, scan_slots=False, scan_origins=False, clear_bounds=False
):
    if clear_bounds and not scan_origins:
        raise ValueError("Clear-bound tracing requires origin tracing")
    if scan_origins and not scan_slots:
        raise ValueError("Origin tracing requires slot tracing")
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
    origins = collections.defaultdict(set)
    clear_ranges = set()
    frame_anchors = set()
    kinds = set()
    for source, target, kind, reserved in struct.iter_unpack(
        "<QQII", memoryview(data)[40:]
    ):
        if (
            not target
            or kind
            not in (
                {1, 2, 3, 4, 5, 6, 7, 8, 9, 10}
                if clear_bounds
                else {1, 2, 3, 4, 5, 6, 7, 8}
                if scan_origins
                else {1, 2, 3, 4, 5}
                if scan_slots
                else {1, 2, 3}
            )
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
        elif kind in (6, 7, 8):
            if not source or source == target:
                raise ValueError("Invalid origin span")
            origins[tuple(sorted((source, target)))].add(
                {
                    6: "conducting-stack",
                    7: "saved-registers",
                    8: "copied-thread-stacks",
                }[kind]
            )
        elif kind in (9, 10):
            if not source or source >= target:
                raise ValueError("Invalid clear range or frame anchor")
            (clear_ranges if kind == 9 else frame_anchors).add((source, target))
    expected = {1, 2, 3, 4, 5} if scan_slots else {1, 2, 3}
    if clear_bounds:
        expected |= {9, 10}
    if not expected.issubset(kinds) or (
        scan_origins and not kinds.intersection({6, 7, 8})
    ):
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
                            {
                                "start": hex(start),
                                "end": hex(end),
                                "originEvents": sorted(origins[(start, end)]),
                            }
                            if scan_origins
                            else [hex(start), hex(end)]
                            for start, end in sorted(spans)
                            if start <= slot < end
                        ],
                    }
                    for slot in sorted(slots[found])
                ]
                if clear_bounds:
                    for slot_record in root["candidateSlots"]:
                        slot = int(slot_record["slot"], 16)
                        slot_record["insideClearRanges"] = [
                            [hex(start), hex(end)]
                            for start, end in sorted(clear_ranges)
                            if start <= slot < end
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
    return {
        "file": str(path),
        "epoch": epoch,
        "records": written,
        "paths": paths,
        "clearRanges": [[hex(a), hex(b)] for a, b in sorted(clear_ranges)],
        "frameAnchors": [[hex(a), hex(b)] for a, b in sorted(frame_anchors)],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("target", nargs="+", type=lambda value: int(value, 0))
    parser.add_argument("--scan-slots", action="store_true")
    parser.add_argument("--scan-origins", action="store_true")
    parser.add_argument("--clear-bounds", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            trace_paths(
                args.trace,
                args.target,
                scan_slots=args.scan_slots,
                scan_origins=args.scan_origins,
                clear_bounds=args.clear_bounds,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
