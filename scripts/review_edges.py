#!/usr/bin/env python3
"""Review the wiring the brain added to itself.

`DIGESTION_SPEC.md` §A10 lets the digester write new edges straight into the live
graph at capped confidence, and defends that with two claims:

    "a bad proposal is damped by the cap, not blocked by a queue"
    "Rare: expect <=1 per week"

The first claim rests on the second, and only the first was ever built. Nothing
measured the rate, so nothing noticed when it ran an order of magnitude above the
figure the design was argued from. This is the review half — the part §A10
promised ("surface for periodic human review") and left as provenance on a field
nobody read.

Why a human at all, when everything else here is graded by evidence: the L0
calibrator scores seed edges only (`brain/calibration.py`, `provenance != "seed"`
-> skip), and it cannot be pointed at these even in principle — an llm edge has
to terminate on a node carrying a tradable symbol for `_score_pair` to have a
price series, and none of them does. They wire factors to private hubs and to
each other. So the cap and this review are the whole of the control surface, and
review is the only half that can ever remove anything.

  python3 scripts/review_edges.py                     # what is waiting, oldest first
  python3 scripts/review_edges.py --stats             # backlog, rate, and the spec gap
  python3 scripts/review_edges.py --contested         # rejections the world keeps re-arguing
  python3 scripts/review_edges.py --json              # same list, for batch reasoning
  python3 scripts/review_edges.py --keep 'power_demand->uranium_price:influences' \
                                  --note "reactor restarts are a real demand channel"
  python3 scripts/review_edges.py --reject 'robotics->power_demand:influences' \
                                  --reason "speculative, no mechanism in the cited story"
  python3 scripts/review_edges.py --batch decisions.jsonl

QUOTE THE KEYS. They contain `->`, and an unquoted `>` is a shell redirect: the
key arrives truncated and the remainder lands as a stray file in the working
directory. `--batch` sidesteps this entirely and is the better path for more
than a couple of decisions.

A KEEP stamps the edge and drops it from the queue; it does NOT raise confidence
past the 0.6 cap, because a human finding a mechanism plausible is not evidence
that it predicts, and only the offline gauntlet may promote structure
(LEARNING.md §2). A REJECT deletes the edge and tombstones the pair, so the next
similar headline cannot walk it back in — and each suppressed re-proposal is
counted, so an edge the world insists on can be argued again rather than being
silently overruled forever.

`--batch` takes JSONL, one decision per line, which is how a review session with
a hundred edges in front of it should hand back its verdicts:

    {"key": "a->b:influences", "verdict": "keep",   "note":   "why it stays"}
    {"key": "c->d:owns",       "verdict": "reject", "reason": "why it goes"}
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "engine"))

from ai_investing.brain.graph import KnowledgeGraph          # noqa: E402
from ai_investing.config import Settings                     # noqa: E402

# What §A10 tells the digester to aim for. Kept as a named constant rather than a
# number inline in a report, because the whole point is to compare against it.
SPEC_EDGES_PER_WEEK = 1.0

ARROW = {"influences": "->", "supplies": "=>", "owns": "owns", "member_of": "in",
         "competes_with": "vs", "correlates_with": "~", "regulated_by": "reg-by"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _label(graph: KnowledgeGraph, nid: str) -> str:
    n = graph.nodes.get(nid)
    return f"{nid} ({n.label})" if n and n.label and n.label != nid else nid


def _age_days(ts: str) -> float:
    try:
        return (_now() - datetime.fromisoformat(ts)).total_seconds() / 86400.0
    except (TypeError, ValueError):
        return float("nan")


def _describe(graph: KnowledgeGraph, e) -> str:
    """One edge, stated as a mechanism a person can agree or disagree with."""
    direction = "raises" if e.sign >= 0 else "lowers"
    strength = e.weight * e.confidence
    return (f"  [{graph.edge_key(e)}]\n"
            f"      {_label(graph, e.src)} up  {direction}  {_label(graph, e.dst)}\n"
            f"      {ARROW.get(e.type, e.type)}  weight {e.weight:.2f} x conf "
            f"{e.confidence:.2f} = {strength:.3f} effective   "
            f"proposed {_age_days(e.proposed_at):.0f}d ago\n"
            f"      because: {e.proposed_by or '(no reason recorded)'}")


def _as_dict(graph: KnowledgeGraph, e) -> dict:
    return {"key": graph.edge_key(e), "src": e.src, "dst": e.dst, "type": e.type,
            "src_label": (graph.nodes.get(e.src).label if e.src in graph.nodes else ""),
            "dst_label": (graph.nodes.get(e.dst).label if e.dst in graph.nodes else ""),
            "sign": e.sign, "weight": e.weight, "confidence": e.confidence,
            "effective": round(e.weight * e.confidence, 4),
            "proposed_at": e.proposed_at, "age_days": round(_age_days(e.proposed_at), 1),
            "proposed_by": e.proposed_by}


def _split(key: str) -> tuple[str, str, str]:
    """'src->dst:type' -> parts. Node ids are `[a-z0-9_]` by construction
    (`propose_node` strips everything else), so neither separator can appear
    inside a name and a plain split is unambiguous.

    The key format is `edge_key()`'s, shared with the calibration report, so it
    is not ours to change — but its `>` is a shell redirect, and an unquoted key
    arrives here silently truncated at the dash while the rest of it becomes an
    empty file in the working directory. That is a confusing five minutes for
    anyone reviewing at speed, so name the real cause instead of the symptom.

    Raises ValueError rather than exiting, so one bad key in a batch of a hundred
    costs that decision and not the other ninety-nine."""
    if "->" not in key and key.endswith("-"):
        raise ValueError("looks truncated at the '>' — the shell read it as a "
                         "redirect; quote the key")
    try:
        pair, type_ = key.rsplit(":", 1)
        src, dst = pair.split("->", 1)
    except ValueError:
        raise ValueError("expected 'src->dst:type' (quoted, because of the '>')")
    if not src.strip() or not dst.strip() or not type_.strip():
        raise ValueError("expected 'src->dst:type' — a part is empty")
    return src.strip(), dst.strip(), type_.strip()


def _stats(graph: KnowledgeGraph) -> dict:
    llm = [e for e in graph.edges if e.provenance == "llm"]
    week_ago = (_now() - timedelta(days=7)).isoformat()
    month_ago = (_now() - timedelta(days=28)).isoformat()
    return {"edges_total": len(graph.edges),
            "edges_llm": len(llm),
            "edges_seed": sum(1 for e in graph.edges if e.provenance == "seed"),
            "pending": len(graph.pending_review()),
            "reviewed": sum(1 for e in llm if e.reviewed_at),
            "rejected": len(graph.rejected),
            "last_7d": graph.proposal_rate(week_ago),
            "last_28d": graph.proposal_rate(month_ago)}


def _print_stats(graph: KnowledgeGraph) -> None:
    s = _stats(graph)
    share = (100.0 * s["edges_llm"] / s["edges_total"]) if s["edges_total"] else 0.0
    per_week = s["last_28d"] / 4.0
    print("graph wiring\n")
    print(f"  edges            {s['edges_total']}  ({s['edges_seed']} curated, "
          f"{s['edges_llm']} llm — {share:.0f}% self-added)")
    print(f"  pending review   {s['pending']}")
    print(f"  reviewed & kept  {s['reviewed']}")
    print(f"  rejected         {s['rejected']}")
    print()
    print(f"  proposed last 7d   {s['last_7d']}")
    print(f"  proposed last 28d  {s['last_28d']}   ({per_week:.1f}/week)")
    print(f"  §A10 expects       <={SPEC_EDGES_PER_WEEK:.0f}/week")
    if per_week > SPEC_EDGES_PER_WEEK:
        # State the gap as a multiple. "40 edges" reads as a backlog to work down;
        # "40x the assumed rate" reads as what it is — the design's premise not
        # holding, which no amount of reviewing fixes.
        print(f"\n  RATE IS {per_week / SPEC_EDGES_PER_WEEK:.0f}x THE SPEC. The cap-not-queue "
              f"argument in §A10\n  assumes rarity; at this rate the review backlog grows "
              f"faster than\n  any human clears it, and llm wiring overtakes curated wiring "
              f"on its own.\n  Reviewing is treating the symptom — the digester's proposal "
              f"bar is the cause.")
    contested = graph.contested_rejections()
    if contested:
        print(f"\n  {len(contested)} rejection(s) being re-argued — see --contested")


def main() -> int:
    ap = argparse.ArgumentParser(description="review llm-proposed graph edges")
    ap.add_argument("--show", type=int, metavar="N", default=None,
                    help="list the N oldest pending edges (default: all)")
    ap.add_argument("--json", action="store_true", help="pending edges as JSON")
    ap.add_argument("--stats", action="store_true", help="backlog and proposal rate")
    ap.add_argument("--contested", action="store_true",
                    help="rejections the digester keeps re-proposing")
    ap.add_argument("--keep", metavar="KEY", help="keep an edge (src->dst:type)")
    ap.add_argument("--note", default="", help="why it was kept")
    ap.add_argument("--reject", metavar="KEY", help="delete and tombstone an edge")
    ap.add_argument("--reason", default="", help="why it was rejected")
    ap.add_argument("--batch", metavar="FILE", help="apply JSONL decisions")
    ap.add_argument("--hygiene", action="store_true",
                    help="report placeholder ('none') nodes and unwired llm nodes")
    ap.add_argument("--prune", action="store_true",
                    help="remove placeholder nodes + their edges (writes the graph)")
    args = ap.parse_args()

    settings = Settings()
    path = settings.brain.graph_path
    # See needs_you.py: load() seeds a graph when the file is missing, so a bad
    # path would have this tool create an empty graph and report a spotless
    # backlog. Refuse instead — the answer to "where is the graph" is never
    # "here is a new one".
    if not os.path.exists(path):
        raise SystemExit(f"no graph at {path} (BRAIN_GRAPH_PATH); refusing to "
                         f"create one — a review tool must not invent the thing "
                         f"it reviews")
    graph = KnowledgeGraph.load(path)
    ts = _now().isoformat()

    if args.hygiene or args.prune:
        victims = [nid for nid in graph.nodes
                   if KnowledgeGraph.is_non_entity(nid)
                   and str(graph.nodes[nid].state or "").startswith("llm-proposed")]
        deg = {}
        for e in graph.edges:
            deg[e.src] = deg.get(e.src, 0) + 1
            deg[e.dst] = deg.get(e.dst, 0) + 1
        print("\ngraph hygiene\n")
        print(f"  nodes {len(graph.nodes)}   edges {len(graph.edges)}\n")
        if victims:
            print("  PLACEHOLDER NODES (a non-answer wired as an entity):")
            for nid in sorted(victims, key=lambda n: -deg.get(n, 0)):
                print(f"    {nid:<34} {deg.get(nid, 0):>3} edges  "
                      f"{graph.nodes[nid].label}")
        else:
            print("  placeholder nodes:  none")
        orphans = graph.orphan_nodes()
        print(f"\n  UNWIRED llm nodes ({len(orphans)}) — vocabulary, not wiring:")
        for nid in orphans[:30]:
            print(f"    {nid:<34} {graph.nodes[nid].label}")
        if len(orphans) > 30:
            print(f"    ... and {len(orphans) - 30} more")
        if not args.prune:
            print("\n  (nothing written — re-run with --prune to remove the "
                  "placeholder nodes)")
            return 0
        out = graph.prune_non_entities(ts)
        graph.save(path)
        print(f"\n  PRUNED {len(out['nodes'])} node(s) and {out['edges']} edge(s); "
              f"each edge tombstoned so the next digest cannot re-add it.")
        print(f"  graph is now {len(graph.nodes)} nodes / {len(graph.edges)} edges.")
        print("  Unwired nodes were NOT removed — an unwired node is inert but "
              "harmless,\n  and some are real companies awaiting wiring "
              "(see graph_gap_scan.py).")
        return 0

    if args.keep or args.reject or args.batch:
        decisions = []
        if args.keep:
            decisions.append({"key": args.keep, "verdict": "keep", "note": args.note})
        if args.reject:
            if not args.reason:
                raise SystemExit("--reject needs --reason: a deletion nobody can "
                                 "explain later is indistinguishable from a bug")
            decisions.append({"key": args.reject, "verdict": "reject",
                              "reason": args.reason})
        applied, failed = 0, []

        if args.batch:
            with open(args.batch) as fh:
                for i, line in enumerate(fh, 1):
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    try:
                        decisions.append(json.loads(line))
                    except json.JSONDecodeError as exc:
                        # Report and carry on. The decisions in a review batch are
                        # independent, so aborting on line 7 of 100 throws away 93
                        # good verdicts to punish one typo — and the reviewer has
                        # no way to know which ones survived.
                        failed.append((f"{args.batch}:{i}", f"bad JSON: {exc}"))

        for d in decisions:
            key = d.get("key", "")
            try:
                src, dst, type_ = _split(key)
            except ValueError as exc:
                failed.append((key or "(no key)", str(exc)))
                continue
            verdict = str(d.get("verdict", "")).lower()
            if verdict == "keep":
                ok = graph.review_edge(src, dst, type_, d.get("note", ""), ts)
            elif verdict == "reject":
                reason = d.get("reason", "")
                if not reason:
                    failed.append((key, "reject without a reason"))
                    continue
                ok = graph.reject_edge(src, dst, type_, reason, ts)
            else:
                failed.append((key, f"unknown verdict {verdict!r}"))
                continue
            if ok:
                applied += 1
            else:
                # Almost always: already reviewed, already rejected, or curated.
                failed.append((key, "no matching llm edge"))

        if applied:
            # save_review, NOT save: this process has been holding a stale copy
            # since it loaded, and the engine adds edges several times a day.
            # A full write here would silently drop anything proposed while the
            # reviewer was reading.
            graph.save_review(path)
        print(f"applied {applied} decision(s) to {path}")
        for key, why in failed:
            print(f"  SKIPPED {key}: {why}")
        if applied:
            print()
            _print_stats(KnowledgeGraph.load(path))
        return 1 if failed else 0

    if args.stats:
        _print_stats(graph)
        return 0

    if args.contested:
        rows = graph.contested_rejections(min_suppressed=1)
        if not rows:
            print("no rejected edge has been re-proposed")
            return 0
        print(f"{len(rows)} rejection(s) the digester has argued with:\n")
        for r in rows:
            print(f"  [{graph.pair_key(r['src'], r['dst'], r['type'])}]  "
                  f"re-proposed {r.get('suppressed', 0)}x since "
                  f"{str(r.get('rejected_at', ''))[:10]}")
            print(f"      rejected because: {r.get('reason', '')}")
            if r.get("last_proposed_by"):
                print(f"      latest argument:  {r['last_proposed_by']}")
        print("\nA rejection argued with many times may be the rejection that was "
              "wrong.\nRe-accept by proposing it again after clearing the tombstone "
              "from\n'rejected_edges' in the graph file.")
        return 0

    pending = graph.pending_review()
    if args.json:
        print(json.dumps({"stats": _stats(graph),
                          "pending": [_as_dict(graph, e) for e in pending]}, indent=1))
        return 0

    if not pending:
        print("nothing pending review")
        _print_stats(graph)
        return 0

    shown = pending[: args.show] if args.show else pending
    print(f"{len(pending)} edge(s) awaiting review — showing {len(shown)}, "
          f"oldest first:\n")
    for e in shown:
        print(_describe(graph, e))
        print()
    _print_stats(graph)
    return 0


if __name__ == "__main__":
    sys.exit(main())
