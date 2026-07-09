"""Heartbeat file for the dead-man's switch. The runner writes it each cycle; the
`--watchdog` command reads it and alerts (and optionally flattens) if it goes stale,
which means the engine crashed or hung while positions may be open."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone


def write_heartbeat(path: str, data: dict) -> None:
    payload = dict(data)
    payload["ts"] = datetime.now(timezone.utc).isoformat()
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w") as fh:
            json.dump(payload, fh)
    except OSError:
        pass


def read_heartbeat(path: str) -> dict | None:
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def age_seconds(hb: dict | None) -> float | None:
    if not hb or "ts" not in hb:
        return None
    try:
        ts = datetime.fromisoformat(hb["ts"])
        return (datetime.now(timezone.utc) - ts).total_seconds()
    except (TypeError, ValueError):
        return None


def is_stale(hb: dict | None, max_seconds: float) -> bool:
    age = age_seconds(hb)
    return age is None or age > max_seconds
