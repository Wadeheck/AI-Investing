#!/usr/bin/env python3
"""Digest the crypto-backfill wave in small rolling batches — no AI session.

The wave campaign (data/digest_v2/crypto_backfill/README.md) was written for
Sonnet operators and a 250-day threshold: wait until a wave's worth of GDELT
days accumulate, then hand-digest. Two problems with that at current reality:
the GDELT crawler now refills continuously (gentle mode, ~days/week), and a
250-day wave in one sitting is a token bomb. This script runs the SAME
campaign protocol against the same free-tier endpoints digest_day.py uses,
whenever BATCH_MIN (20) fetched-but-undigested days have accumulated.

Scope discipline: a day is eligible ONLY once its GDELT headlines exist in
news_archive_gdelt_crypto.jsonl. Staged days that so far have only Wu/listing
content must wait — the amend-file marks a day permanently done, so digesting
early would silently drop that day's GDELT headlines when they later arrive.

Per day, per campaign README: existing corpus events are shown alongside the
staged headlines; the model emits NEW events only for uncovered stories plus
add_nodes amendments — append-only, never touching events/. After a batch,
_merge_amendments.py folds everything into the ledger and impulses.

  python3 scripts/crypto_wave_digest.py              # digest if >= 20 pending
  python3 scripts/crypto_wave_digest.py --force      # digest whatever is pending
  python3 scripts/crypto_wave_digest.py --dry-run
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

from ai_investing.brain.graph import KnowledgeGraph          # noqa: E402
from ai_investing.config import Settings                     # noqa: E402
from ai_investing.data.news import _call_llm, _extract_json  # noqa: E402
from ai_investing.util import atomic                         # noqa: E402

BRIEF = ROOT / "docs" / "data-pipeline" / "SONNET_DIGEST_BRIEF.md"
D2 = ROOT / "data" / "digest_v2"
CAMPAIGN = D2 / "crypto_backfill"
DAYS = CAMPAIGN / "days"
AMEND_OUT = D2 / "events_amend_crypto"
EVENTS = D2 / "events"

BATCH_MIN = 20      # digest as soon as this many GDELT days are pending
BATCH_MAX = 40      # per run, so one invocation stays bounded
CHUNK = 20          # headlines per LLM call

CAMPAIGN_RULES = """
CAMPAIGN ADDENDUM (crypto-backfill amendments — overrides nothing, adds rules):
- The day you are digesting ALREADY has events from the Guardian corpus
  (listed below as EXISTING EVENTS). Do not re-describe covered stories.
- Emit a NEW event only for a story the existing events do not cover.
- When a staged story shows an EXISTING event also belongs on a crypto node
  it lacks, emit {"amend": "add_nodes", "event_key": <existing key>,
  "nodes": [<node ids>]} instead of a new event.
- A story already covered correctly: emit nothing for it.
- Temporal integrity is absolute: you live on the day being digested and
  know nothing after it. Headlines carry their real publication ts.
"""


def pending_days() -> list[str]:
    """GDELT-fetched days (2023-07-01+) with no amendment file yet."""
    fetched = set()
    try:
        for line in open(ROOT / "data" / "news_archive_gdelt_crypto.jsonl"):
            try:
                fetched.add(json.loads(line)["date"])
            except (json.JSONDecodeError, KeyError):
                pass
    except OSError:
        return []
    return sorted(d for d in fetched
                  if d >= "2023-07-01" and not (AMEND_OUT / f"{d}.json").exists())


def existing_events(date: str) -> list[dict]:
    try:
        evs = json.loads((EVENTS / f"{date}.json").read_text()).get("events", [])
    except (OSError, json.JSONDecodeError):
        return []
    return [{"event_key": e.get("event_key", ""), "summary": e.get("summary", ""),
             "nodes": e.get("nodes", [])} for e in evs]


def staged_headlines(date: str) -> list[dict]:
    out = []
    try:
        for line in (DAYS / f"{date}.jsonl").read_text().splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    except OSError:
        pass
    return out


def digest_day(date: str, settings, graph, dry: bool) -> bool:
    heads = staged_headlines(date)
    if not heads:
        print(f"  {date}: nothing staged — recording empty amendment", flush=True)
        if not dry:
            atomic.write_json(AMEND_OUT / f"{date}.json",
                              {"events": [], "amendments": [],
                               "source": "scripts/crypto_wave_digest.py"}, indent=1)
        return True
    exist = existing_events(date)
    node_ids = ", ".join(f"{n.id} [{n.label}]" if getattr(n, "label", "") else n.id
                         for n in graph.nodes.values() if n.type != "asset")
    brief = BRIEF.read_text()
    events, amendments = [], []
    for i in range(0, len(heads), CHUNK):
        batch = heads[i:i + CHUNK]
        lines = "\n".join(
            f"{j}. [{h.get('ts','')[11:16]}Z | {h.get('source','?')}] {h.get('title','')}"
            f"{' — ' + h['summary'][:300] if h.get('summary') else ''}"
            for j, h in enumerate(batch, 1))
        ex = "\n".join(f"- {e['event_key']}: {e['summary'][:160]} (nodes: "
                       f"{', '.join(e['nodes'][:8])})" for e in exist) or "(none)"
        prompt = (f"{brief}\n\n---\n{CAMPAIGN_RULES}\n\n"
                  f"KNOWN GRAPH NODES (use ONLY these ids):\n{node_ids}\n\n"
                  f"DATE BEING DIGESTED: {date}\n\nEXISTING EVENTS FOR {date}:\n{ex}\n\n"
                  f"STAGED HEADLINES:\n{lines}\n\n"
                  f'Return ONLY JSON: {{"events": [...], "amendments": [...]}}. '
                  f"New events follow the brief's full schema (polarity NEVER 0). "
                  f"Amendments follow the addendum's add_nodes form.")
        if dry:
            continue
        raw = _call_llm(prompt, settings, max_tokens=8000, tier="fast", json_mode=True)
        parsed = _extract_json(raw or "") or {}
        if isinstance(parsed.get("events"), list):
            events.extend(e for e in parsed["events"] if isinstance(e, dict))
        if isinstance(parsed.get("amendments"), list):
            amendments.extend(a for a in parsed["amendments"] if isinstance(a, dict))
    if dry:
        print(f"  {date}: {len(heads)} staged headlines, {len(exist)} existing events "
              f"-> {(len(heads)+CHUNK-1)//CHUNK} call(s)")
        return True

    now = datetime.now(timezone.utc).isoformat()
    valid = {n.id for n in graph.nodes.values()}
    known_keys = {e["event_key"] for e in exist}
    for e in events:
        e["nodes"] = [n for n in (e.get("nodes") or []) if n in valid]
        e.setdefault("ts", f"{date}T12:00:00Z")
        e["digested_by"] = "automated"
        e["digested_at"] = now
    amendments = [a for a in amendments
                  if a.get("amend") == "add_nodes" and a.get("event_key") in known_keys
                  and [n for n in (a.get("nodes") or []) if n in valid]]
    for a in amendments:
        a["nodes"] = [n for n in a["nodes"] if n in valid]
    # Empty output IS valid here (unlike digest_day.py): most staged stories
    # should already be covered by the Guardian corpus — that's the campaign
    # working, not the model failing. The file still gets written so the day
    # counts as done.
    atomic.write_json(AMEND_OUT / f"{date}.json",
                      {"events": events, "amendments": amendments,
                       "source": "scripts/crypto_wave_digest.py"}, indent=1)
    print(f"  {date}: {len(events)} new events, {len(amendments)} amendments "
          f"({len(heads)} staged, {len(exist)} pre-existing)", flush=True)
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="digest pending days even below the batch threshold")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    # Refresh staging first — idempotent, folds newly crawled GDELT days in.
    subprocess.run([sys.executable, str(CAMPAIGN / "_stage.py")],
                   cwd=str(CAMPAIGN), capture_output=True, timeout=600)
    todo = pending_days()
    if not todo:
        print("wave backlog empty")
        return 0
    if len(todo) < BATCH_MIN and not args.force:
        print(f"{len(todo)} day(s) pending — below batch of {BATCH_MIN}, waiting")
        return 0
    todo = todo[:BATCH_MAX]
    print(f"digesting {len(todo)} day(s): {todo[0]} .. {todo[-1]}", flush=True)

    settings = Settings()
    graph = KnowledgeGraph.load(settings.brain.graph_path)
    AMEND_OUT.mkdir(parents=True, exist_ok=True)
    done = sum(1 for d in todo if digest_day(d, settings, graph, args.dry_run))

    if not args.dry_run and done:
        print("merging amendments into ledger + impulses ...", flush=True)
        r = subprocess.run([sys.executable, str(D2 / "_merge_amendments.py")],
                           cwd=str(D2), capture_output=True, text=True, timeout=900)
        tail = [l for l in (r.stdout or "").splitlines() if "impulses" in l.lower()]
        print(f"  {tail[-1].strip() if tail else f'merge exit {r.returncode}'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
