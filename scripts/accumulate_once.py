#!/usr/bin/env python3
"""One-shot feed accumulation for cron: pull all RSS/alt feeds into the live
archive and the brain store, then exit. Safe to run repeatedly (dedupes)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from ai_investing.config import Settings
from ai_investing.brain.store import BrainStore
from ai_investing.research.accumulate import run_once

if __name__ == "__main__":
    s = Settings()
    n = run_once(s, BrainStore(s.brain.db_path))
    print(f"accumulated {n} new headlines")
