"""Require source-bound startup milestones after a successful native smoke."""

import json
import sys
from pathlib import Path


def verify(path):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines()]
    native = [
        row
        for row in rows
        if row.get("stage") == "startup-diagnostic" and row.get("source") == "native"
    ]
    for index, enter in enumerate(native):
        if enter.get("phase") != "open_window_enter":
            continue
        identity = (
            enter.get("nonce"),
            enter.get("pid"),
            enter.get("request_id"),
            enter.get("window_id"),
        )
        if not all(identity):
            continue
        returned = any(
            row.get("phase") == "open_window_returned"
            and (
                row.get("nonce"),
                row.get("pid"),
                row.get("request_id"),
                row.get("window_id"),
            )
            == identity
            for row in native[index + 1 :]
        )
        logger = any(
            row.get("stage") == "startup-log"
            and row.get("phase") == "logger_installed"
            and (row.get("nonce"), row.get("pid")) == identity[:2]
            for row in rows
        )
        if returned and logger:
            return
    raise ValueError(
        "Matching host startup, window-open and logger evidence is required"
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Expected a native JSONL evidence path")
    verify(sys.argv[1])
