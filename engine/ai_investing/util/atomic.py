"""Crash-safe file writes.

`json.dump(state, open(path, "w"))` truncates the target BEFORE writing. If the
machine loses power in that window -- and this is about to run 24/7 on a mini
PC with no UPS -- the file is left empty or half-written, and the book it held
is gone. The positions, the cost basis, the forward record the learning spine
grades itself against: all unrecoverable, because the only copy was the file
being overwritten.

The fix is the standard durable-replace dance:

    write to a temp file in the SAME directory  (same filesystem, so the
                                                 rename below is atomic)
    flush + fsync                               (bytes actually on the platter,
                                                 not just in the page cache)
    os.replace onto the target                  (atomic: readers see either the
                                                 old file or the new one, never
                                                 a torn one)

A crash can therefore lose the newest write, never the file.
"""
from __future__ import annotations

import json
import os
from typing import Any


def write_text(path: str, text: str) -> None:
    """Atomically replace `path` with `text`."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    tmp = os.path.join(directory, f".{os.path.basename(path)}.tmp")
    with open(tmp, "w") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())          # durable before we swap it in
    os.replace(tmp, path)


def write_json(path: str, obj: Any, indent: int | None = None) -> None:
    """Atomically replace `path` with `obj` serialised as JSON.

    Serialisation happens BEFORE the file is touched: an object that fails to
    encode leaves the previous good state untouched rather than truncated.

    `allow_nan=False` is the point of this function as much as the atomic
    rename is. `NaN` and `Infinity` are NOT valid JSON, but Python's encoder
    emits them anyway and its decoder reads them back — so a single non-finite
    number entering any state file **persists across every restart forever**,
    and nothing notices, because NaN compares false to everything. A guard
    like `if cash < 0: halt` does not fire on NaN. That is how `shadow.json`
    came to hold `NaN` cash (§4A).

    Refusing here means a bad value raises at the moment it is produced, with
    the previous good state still on disk — exactly the property the docstring
    above already promised, applied to the one class of value that was slipping
    through it.
    """
    write_text(path, json.dumps(obj, indent=indent, allow_nan=False))


def _refuse_non_finite(token: str) -> Any:
    """`json.load`'s hook for the three tokens that are not legal JSON.

    Without this, a file written by an older build (or by hand) re-admits the
    very value `write_json` now refuses to create, and the corruption survives
    the fix.
    """
    raise ValueError(f"{token} is not valid JSON and must not enter a state file")


def read_json(path: str, default: Any = None) -> Any:
    """Read JSON, tolerating absence and corruption.

    A file damaged by a pre-atomic-write crash should not take the engine down
    on startup; the caller gets the default and rebuilds. A file holding
    `NaN`/`Infinity` counts as corrupt for exactly the same reason — see
    `write_json` — so it is rebuilt rather than inherited.
    """
    try:
        with open(path) as fh:
            return json.load(fh, parse_constant=_refuse_non_finite)
    except (OSError, json.JSONDecodeError, ValueError):
        return default
