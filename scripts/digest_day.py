#!/usr/bin/env python3
"""Digest a day's headlines into graph events — without an AI session.

Corpus digestion has always been done by Sonnet subagents reading
docs/data-pipeline/SONNET_DIGEST_BRIEF.md and hand-writing
data/digest_v2/events/<date>.json. That works, and it scores 100% on the golden
set — but it only happens when someone is driving. On a box that is supposed to
run 24/7 unattended, "waits for a human" is a design flaw, not a workflow: the
2026-08-02 corpus was simply missing because nobody ran it.

This closes that. It drives the SAME brief against the same cloud endpoints the
live tagger uses (three of them, 15M free tokens/day against 3.2M of current
demand), so digestion happens on a timer whether anyone is watching or not.

HONEST TRADE-OFF, stated rather than buried: these models will not match
Sonnet's 100% on the golden set. But a corpus digested every day at lower
fidelity beats one digested perfectly whenever a human is available — gaps in
training data are worse than noise in it, because a missing day is silently
treated as "nothing happened". Sonnet remains available for backfill and for
re-digesting anything this flags as low confidence.

  python3 scripts/digest_day.py                # yesterday (the usual case)
  python3 scripts/digest_day.py 2026-08-02     # a specific day
  python3 scripts/digest_day.py --catch-up 7   # any undigested day in the last 7
  python3 scripts/digest_day.py --dry-run
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

from ai_investing.brain.graph import KnowledgeGraph          # noqa: E402
from ai_investing.config import Settings                     # noqa: E402
from ai_investing.data.news import _call_llm, _extract_json  # noqa: E402
from ai_investing.util import atomic                         # noqa: E402

BRIEF = ROOT / "docs" / "data-pipeline" / "SONNET_DIGEST_BRIEF.md"
OUT_DIR = ROOT / "data" / "digest_v2" / "events"
ARCHIVES = ["news_archive_guardian.jsonl", "news_archive_live.jsonl"]
CHUNK = 25          # headlines per call; the brief is long, so keep batches modest


def headlines_for(date: str) -> list[dict]:
    """Every headline recorded for `date`, across archives, de-duplicated."""
    seen, out = set(), []
    for name in ARCHIVES:
        p = ROOT / "data" / name
        if not p.exists():
            continue
        for line in p.read_text(errors="replace").splitlines():
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            rows = d.get("headlines") if d.get("date") == date else None
            if not rows:
                continue
            for h in rows:
                key = (h.get("title") or "")[:80].lower()
                if key and key not in seen:
                    seen.add(key)
                    out.append(h)
    return out


def digest(date: str, settings, graph, dry: bool) -> int:
    heads = headlines_for(date)
    if not heads:
        print(f"  {date}: no headlines archived — nothing to digest")
        return 0
    node_ids = ", ".join(f"{n.id} [{n.label}]" if getattr(n, "label", "") else n.id
                         for n in graph.nodes.values() if n.type != "asset")
    brief = BRIEF.read_text()
    events: list[dict] = []
    for i in range(0, len(heads), CHUNK):
        batch = heads[i:i + CHUNK]
        lines = "\n".join(
            f"{j}. [{h.get('ts','')[11:16]}Z | {h.get('source','?')}] {h.get('title','')}"
            f"{' — ' + h['summary'][:300] if h.get('summary') else ''}"
            for j, h in enumerate(batch, 1))
        prompt = (f"{brief}\n\n---\n\nKNOWN GRAPH NODES (use ONLY these ids):\n{node_ids}\n\n"
                  f"DATE BEING DIGESTED: {date}\n\nHEADLINES:\n{lines}\n\n"
                  f'Return ONLY JSON: {{"events": [ ... ]}} following the schema in §'
                  f"the brief. Every event needs: summary, headline, source, type, nodes, "
                  f"polarity (NEVER 0), magnitude, confidence, manipulation_likelihood, "
                  f"emotion, emotion_intensity, novelty, event_key.")
        print(f"    batch {i+1}-{i+len(batch)} of {len(heads)} ...", flush=True)
        if dry:
            continue
        raw = _call_llm(prompt, settings, max_tokens=8000, tier="fast", json_mode=True)
        parsed = _extract_json(raw or "") or {}
        got = parsed.get("events")
        if isinstance(got, list):
            events.extend(e for e in got if isinstance(e, dict))

    if dry:
        print(f"  {date}: {len(heads)} headlines would be digested in "
              f"{(len(heads)+CHUNK-1)//CHUNK} calls")
        return 0
    if not events:
        print(f"  {date}: model returned no usable events — NOT writing an empty "
              f"file (an empty day reads as 'nothing happened')")
        return 1

    now = datetime.now(timezone.utc).isoformat()
    valid = {n.id for n in graph.nodes.values()}
    for e in events:
        e["nodes"] = [n for n in (e.get("nodes") or []) if n in valid]
        e.setdefault("ts", f"{date}T12:00:00Z")
        e["digested_by"] = "automated"        # provenance: not Sonnet-quality
        e["digested_at"] = now
    atomic.write_json(OUT_DIR / f"{date}.json",
                      {"events": events, "redigest": [],
                       "source": "scripts/digest_day.py"}, indent=1)
    signed = sum(1 for e in events if abs(float(e.get("polarity", 0) or 0)) > 1e-9)
    tagged = sum(1 for e in events if e.get("nodes"))
    print(f"  {date}: {len(events)} events written "
          f"({tagged} tagged, {signed} signed) -> {OUT_DIR.name}/{date}.json")
    derive_impulses()
    return 0


def derive_impulses() -> None:
    """Re-derive news_impulses_v2.jsonl from the events just written.

    events/*.json is the source of truth; the impulse file is DERIVED from it by
    _merge_amendments.py (impulse = polarity x magnitude x novelty x confidence x
    (1 - manipulation_likelihood), amendments applied). Automating the digest
    without automating this step left the two out of step: events for 2026-08-03
    existed while the impulse file still ended on 08-02, so the training corpus
    silently stopped a day short of the corpus it is built from.

    Cheap to re-run (it rebuilds the whole file deterministically) and safe on
    failure: a stale impulse file is a known state, a half-written one is not.
    """
    merge = ROOT / "data" / "digest_v2" / "_merge_amendments.py"
    if not merge.exists():
        print("  (no _merge_amendments.py — impulses not re-derived)")
        return
    print("  re-deriving impulses from events ...", flush=True)
    try:
        r = subprocess.run([sys.executable, str(merge)], cwd=str(merge.parent),
                           capture_output=True, text=True, timeout=900)
        tail = [l for l in (r.stdout or "").splitlines() if "impulses_v2" in l]
        print(f"    {tail[-1].strip() if tail else f'exit {r.returncode}'}")
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"    FAILED: {type(exc).__name__}: {str(exc)[:100]} — "
              f"events are written; impulses stay at their last good state")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("date", nargs="?", default="")
    ap.add_argument("--catch-up", type=int, default=0,
                    help="digest any undigested day within the last N days")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    settings = Settings()
    graph = KnowledgeGraph.load(settings.brain.graph_path)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.catch_up:
        today = datetime.now(timezone.utc).date()
        days = [(today - timedelta(days=k)).isoformat() for k in range(1, args.catch_up + 1)]
        todo = [d for d in days if not (OUT_DIR / f"{d}.json").exists()]
        if not todo:
            print(f"nothing undigested in the last {args.catch_up} days")
            return 0
        print(f"catching up {len(todo)} day(s): {', '.join(sorted(todo))}")
        rc = 0
        for d in sorted(todo):
            rc |= digest(d, settings, graph, args.dry_run)
        return rc

    date = args.date or (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    if (OUT_DIR / f"{date}.json").exists() and not args.dry_run:
        print(f"{date} already digested — skipping (delete the file to redo)")
        return 0
    return digest(date, settings, graph, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
