#!/usr/bin/env python3
"""Does the digester's node reference still describe the graph it teaches?

§4.34: the brief's own node reference had drifted **12 nodes behind** the graph
it describes, and nobody noticed because nothing compared them. The fix at the
time was to transcribe the missing twelve. That closed the instance and left the
mechanism — a reference maintained by hand against a graph that grows weekly
will drift again, and the next drift is just as silent.

`SONNET_DIGEST_BRIEF.md` §7 is injected verbatim as the digester's system prompt
and says "Tag ONLY these ids". So drift has two distinct costs, and they are not
symmetric:

  MISSING  a node exists in the graph and not in the brief. The digester cannot
           tag it, so every story about it lands nowhere. This is the §4.34
           failure and the expensive direction — silent under-coverage.
  STALE    a node is in the brief and not in the graph. The digester tags an id
           that does not exist; the runner rejects it. Noisy, wasteful, but it
           cannot corrupt the web.

Also checks the COUNTS the brief states in its own headings ("all 140 nodes",
"### Factors (68)"), because a heading that disagrees with its own table is how
a reader concludes the reference is complete when it is not.

Read-only. No LLM, no network.
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

BRIEF = ROOT / "docs" / "data-pipeline" / "SONNET_DIGEST_BRIEF.md"

# Assets are deliberately absent from the brief: "Assets are not taggable — the
# graph maps nodes->assets". Comparing them would report ~460 false positives.
TAGGABLE_TYPES = {"factor", "theme", "sector", "actor", "commodity"}


def _brief_ids(text: str) -> set[str]:
    """Every node id declared in §7 — from its TABLE ROWS and its comma-separated
    prose lists, not from every backtick in the section.

    The first version matched any `backticked_word`, which swept up prose
    references to a JSON field (`equilibrium`) and an edge type (`supplies`) and
    reported them as stale node ids. A drift detector that cries wolf gets
    ignored, which is worse than not having one — so it reads only the two
    places an id is actually DECLARED:

      | `node_id` | +1 means ... |          <- the factor/theme/actor tables
      `a`, `b`, `c`                          <- the commodity/sector list lines

    A prose sentence mentioning a backticked word is neither.
    """
    start = text.index("## 7. THE NODE REFERENCE")
    end = text.index("## 8.", start)
    ids: set[str] = set()
    for line in text[start:end].splitlines():
        line = line.strip()
        m = re.match(r"^\|\s*`([a-z0-9_]+)`\s*\|", line)
        if m:
            ids.add(m.group(1))
            continue
        # a list line is backticked ids separated by commas and nothing else
        if line.startswith("`") and re.fullmatch(r"(`[a-z0-9_]+`,?\s*)+", line):
            ids.update(re.findall(r"`([a-z0-9_]+)`", line))
    return ids


def _plural(t: str) -> str:
    """`commodity` -> `commodities`, which the brief's heading actually says.
    Naive `t + "s"` gave "commoditys" and reported a mismatch that was mine."""
    return t[:-1] + "ies" if t.endswith("y") else t + "s"


def _stated_counts(text: str) -> dict[str, int]:
    start = text.index("## 7. THE NODE REFERENCE")
    end = text.index("## 8.", start)
    out = {}
    for name, n in re.findall(r"### (\w[\w &-]*?) \((\d+)\)", text[start:end]):
        out[name.strip().lower()] = int(n)
    m = re.search(r"all (\d+) nodes", text[start:end])
    if m:
        out["_total"] = int(m.group(1))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quiet", action="store_true", help="only report problems")
    args = ap.parse_args(argv)

    from ai_investing.brain.graph import KnowledgeGraph
    from ai_investing.config import Settings

    settings = Settings()
    graph = KnowledgeGraph.load(settings.brain.graph_path)
    taggable = {n.id: n.type for n in graph.nodes.values() if n.type in TAGGABLE_TYPES}

    text = BRIEF.read_text()
    in_brief = _brief_ids(text)
    stated = _stated_counts(text)

    missing = sorted(set(taggable) - in_brief)          # graph has it, brief does not
    stale = sorted(in_brief - set(taggable))            # brief has it, graph does not

    by_type: dict[str, int] = {}
    for t in taggable.values():
        by_type[t] = by_type.get(t, 0) + 1

    if not args.quiet:
        print("digester node reference vs the live graph\n")
        print(f"  graph taggable nodes : {len(taggable)}")
        print(f"  ids in brief §7      : {len(in_brief)}")
        print(f"  brief says           : {stated.get('_total', '?')}\n")
        print(f"  {'type':12s}{'in graph':>10}{'brief says':>12}")
        for t in sorted(by_type):
            said = stated.get(_plural(t), stated.get(t, "-"))
            flag = "" if said == by_type[t] else "   <-- disagrees"
            print(f"  {t:12s}{by_type[t]:>10}{str(said):>12}{flag}")

    bad = False
    if missing:
        bad = True
        print(f"\n!! MISSING from the brief ({len(missing)}) — the digester cannot "
              f"tag these, so every story about them lands nowhere:")
        for nid in missing:
            print(f"     {nid:34s} ({taggable[nid]})")
    if stale:
        bad = True
        print(f"\n!! STALE in the brief ({len(stale)}) — tagged ids the graph will "
              f"reject:")
        for nid in stale:
            print(f"     {nid}")

    mismatched = [(t, by_type[t], stated.get(_plural(t), stated.get(t)))
                  for t in sorted(by_type)
                  if stated.get(_plural(t), stated.get(t)) not in (None, by_type[t])]
    if mismatched or (stated.get("_total") not in (None, len(taggable))):
        bad = True
        print(f"\n!! COUNTS in the brief's own headings disagree with its table. "
              f"A heading that overstates completeness is how a reader concludes "
              f"the reference is finished when it is not.")
        for t, actual, said in mismatched:
            print(f"     {t}: table has {actual}, heading says {said}")
        if stated.get("_total") not in (None, len(taggable)):
            print(f"     total: graph has {len(taggable)}, brief says {stated['_total']}")

    if not bad:
        print("\n  ✓ the brief describes exactly the graph it teaches")
        return 0
    print("\n  The brief is injected VERBATIM as the digester's system prompt and "
          "says\n  \"Tag ONLY these ids\" — so this drift is what the digester "
          "believes.\n  Fix the brief, then re-run its §15 golden-set audit.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
