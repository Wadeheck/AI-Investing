#!/usr/bin/env python3
"""Periodic GPU retraining entry point for the isolated NN challengers.

Run this on the ThinkStation/P40, never on the ProDesk.  Each challenger
builds point-in-time samples, recalibrates, runs its walk-forward gate, and
promotes only an out-of-sample-improving artifact.  A failed/rejected fit
leaves the incumbent untouched.
"""
from __future__ import annotations
import os
import subprocess
import sys


def main() -> int:
    env = os.environ.copy()
    # "auto" rather than "cuda": the P40 is preferred, but the retrain must not
    # silently fail when the GPU is down (driver not loaded, device nodes absent,
    # a kernel upgrade that hasn't been rebooted). "auto" picks cuda when
    # available and the CPU reference implementation otherwise — the same fallback
    # each challenger already ships for its own "auto" default.
    env.update({"CUDA_VISIBLE_DEVICES": "0", "NN3_DEVICE": "auto", "NN4_DEVICE": "auto"})
    base = os.path.dirname(os.path.abspath(__file__))
    results = []
    for name in ("nn_v3_runner.py", "nn_v4_runner.py"):
        path = os.path.join(base, name)
        results.append(subprocess.run([sys.executable, "-u", path], env=env).returncode)
    return 1 if any(code != 0 for code in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
