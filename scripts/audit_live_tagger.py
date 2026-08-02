#!/usr/bin/env python3
"""Score the LIVE tagger against the golden set.

The corpus digester (Sonnet) has always been audited — it scores 100% here.
The tagger that actually runs in the engine every five minutes never was, and
that is where the damage was: it returned polarity 0 on 57% of events, and
since `impulse = polarity x magnitude x credibility`, a zero polarity means the
event reaches the graph as nothing at all. Half the brain's reading was being
silently thrown away.

This script is the instrument that makes that visible, so prompt changes are
measured instead of asserted. Same 50 hand-labelled items the corpus digester
is held to.

  python3 scripts/audit_live_tagger.py            # score the current tagger
  python3 scripts/audit_live_tagger.py --batch 25 # smaller LLM batches

Scored dimensions, in order of how much they matter to the field:

  UNSIGNED   share of events with polarity 0 -> contribute literally nothing
  SIGN       of the events it did sign, how many point the right way
  ORIGIN     did it tag the node where the shock ORIGINATES (Hormuz -> oil_supply,
             not just geopolitical_tension)
  SEEN       did the headline produce an event at all
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

from ai_investing.brain.events import extract_events          # noqa: E402
from ai_investing.brain.graph import KnowledgeGraph           # noqa: E402
from ai_investing.config import Settings                      # noqa: E402

GOLD = ROOT / "data" / "digest_v2" / "golden_set.jsonl"


def _norm(s: str) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())[:60]


def _model_label(settings) -> str:
    """Name the model that will actually answer, so results are attributable."""
    if settings.llm_prefer_local:
        return f"{settings.local_llm_model_fast} (local-first)"
    if settings.anthropic_api_key:
        return "anthropic"
    if settings.byteplus_api_key:
        return settings.byteplus_model_fast
    if settings.deepseek_api_key:
        return settings.deepseek_model
    return settings.local_llm_model_fast


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=50)
    ap.add_argument("--json", action="store_true", help="machine-readable result")
    ap.add_argument("--model", default="", help="override the fast-tier model id")
    ap.add_argument("--headline-batch", type=int, default=0,
                    help="headlines per LLM call; _BATCH exists because qwen3:8b "
                         "collapses above ~10, a limit a stronger model may not share")
    args = ap.parse_args()

    gold = [json.loads(l) for l in GOLD.read_text().splitlines() if l.strip()]
    settings = Settings()
    if args.model:
        # cloud model only — overriding the local name too would point Ollama at
        # a model it does not have, and the run would silently measure the
        # keyword fallback instead of the model under test
        settings.byteplus_model_fast = args.model
    if args.headline_batch:
        from ai_investing.brain import events as _ev
        _ev._BATCH = args.headline_batch
    graph = KnowledgeGraph.load(settings.brain.graph_path)

    headlines = [{"title": g["title"], "source": g.get("source", ""),
                  "summary": g.get("summary", ""), "published": g.get("ts", "")}
                 for g in gold]

    events: list[dict] = []
    for i in range(0, len(headlines), args.batch):
        chunk = headlines[i:i + args.batch]
        print(f"  tagging {i + 1}-{i + len(chunk)} of {len(headlines)} ...", flush=True)
        events.extend(extract_events(chunk, graph, settings))

    # index events by headline; the tagger may merge duplicates
    by_head: dict[str, dict] = {}
    for ev in events:
        for key in (_norm(ev.get("headline", "")), _norm(ev.get("summary", ""))):
            if key and key not in by_head:
                by_head[key] = ev

    seen = signed = sign_ok = origin_ok = usable = 0
    misses: list[str] = []
    unsigned_items: list[str] = []
    wrong_sign: list[str] = []

    for g in gold:
        exp = g.get("expect", {})
        req = list(exp.get("req") or [])
        signs = exp.get("signs") or {}
        ev = by_head.get(_norm(g["title"]))
        if ev is None:
            misses.append(g["title"][:70])
            continue
        seen += 1
        pol = float(ev.get("polarity", 0.0) or 0.0)
        nodes = list(ev.get("nodes") or [])
        hit = next((n for n in req if n in nodes), None)   # the origin it found
        if hit:
            origin_ok += 1
        if abs(pol) < 1e-9:
            unsigned_items.append(g["title"][:70])
        else:
            signed += 1
            # Score the sign against the node the model ACTUALLY tagged. Falling
            # back to the first expected node would credit a right sign on a
            # node it never chose.
            want = signs.get(hit, 0) if hit else next(
                (signs[n] for n in req if n in signs), 0)
            if want and (pol > 0) == (want > 0):
                sign_ok += 1
                if hit:
                    usable += 1       # right node AND right direction
            elif want:
                wrong_sign.append(f"{g['title'][:60]} (got {pol:+.2f}, want {want:+d})")

    n = len(gold)
    pct = lambda a, b: (100.0 * a / b) if b else 0.0     # noqa: E731
    res = {
        "n": n, "seen": seen, "signed": signed,
        "unsigned_pct": round(pct(n - seen + len(unsigned_items), n), 1),
        "sign_acc_pct": round(pct(sign_ok, signed), 1),
        "origin_pct": round(pct(origin_ok, n), 1),
        "usable_pct": round(pct(usable, n), 1),
        "seen_pct": round(pct(seen, n), 1),
        "model": _model_label(settings),
        "batch": args.headline_batch or None,
    }
    if args.json:
        print(json.dumps(res, indent=1))
        return 0

    print("\n" + "=" * 62)
    print(f"  LIVE TAGGER AUDIT — {res['model']} — {n} golden items")
    print("=" * 62)
    print(f"  SEEN      {seen}/{n} ({res['seen_pct']:.0f}%)   headline produced an event")
    print(f"  UNSIGNED  {res['unsigned_pct']:.0f}%          polarity 0 => contributes NOTHING")
    print(f"  SIGN      {sign_ok}/{signed} ({res['sign_acc_pct']:.0f}%)   of signed events, direction correct")
    print(f"  ORIGIN    {origin_ok}/{n} ({res['origin_pct']:.0f}%)   tagged the node the shock originates on")
    print(f"  USABLE    {usable}/{n} ({res['usable_pct']:.0f}%)   right node AND right direction <- the one that matters")
    if unsigned_items:
        print(f"\n  discarded as unsigned ({len(unsigned_items)}):")
        for t in unsigned_items[:8]:
            print(f"    · {t}")
    if wrong_sign:
        print(f"\n  wrong direction ({len(wrong_sign)}):")
        for t in wrong_sign[:8]:
            print(f"    · {t}")
    if misses:
        print(f"\n  no event produced ({len(misses)}):")
        for t in misses[:8]:
            print(f"    · {t}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
