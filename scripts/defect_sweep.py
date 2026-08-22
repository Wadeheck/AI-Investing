#!/usr/bin/env python3
"""Ask the questions that actually found the defects — mechanically, every time.

WHY THIS EXISTS. On 2026-08-21/22 a review found **17 defects** (§4.37–§4.53) in
a system that had 645 passing tests. Two of them were introduced *during* the
review. The uncomfortable read is that the defect rate tracks how hard someone
looks — which makes quality a function of who is on shift and how alert they are.
That is not a property you want in something trading unattended.

But the 17 were not found by 17 different insights. Sorted by the QUESTION that
surfaced each, they collapse into a handful, and most of them are mechanical:

    Q1  "what is the unit of observation?"    §4.37 §4.47 §4.53        3
    Q2  "compared with what?"                 §4.6  §4.44 §4.51        3
    Q3  "where else does this pattern live?"  §4.14 §4.23 §4.36 §4.49
                                              §4.51 §4.52 §4.53        7   <-- biggest
    Q4  "who else reads this field?"          §4.45                    1
    Q5  "has this test ever actually failed?" §4.44 §4.48 (+8 vacuous)  2
    Q6  "what does the NEGATIVE answer mean?" §4.52                    1

**13 of 17 came from four questions that a script can ask.** So it asks them.

WHAT THIS IS NOT. Not a linter and not a substitute for thinking. Every finding
here is a QUESTION, not a verdict — the output is a list of places worth looking,
ranked so the highest-yield shape comes first. A clean sweep does not mean there
are no defects; it means these four questions have no obvious answers left.

Read-only. No network, no LLM, no imports of the code it scans.
"""
import argparse
import ast
import collections
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN = [ROOT / "engine" / "ai_investing", ROOT / "scripts"]
TESTS = ROOT / "engine" / "tests"

# Names whose absence is dangerous to paper over with a number. A missing price
# is not 0.0 (§4A); a missing volatility is not 2% (§4.51). These are the words
# the codebase actually uses for such things.
RISKY = ("price", "px", "vol", "qty", "equity", "cash", "notional", "weight",
         "impact", "signal", "ratio", "gain", "rate", "size", "basis", "mid")

# A rate is not evidence without something saying what its sample is worth.
RATE_KEYS = ("hit", "hit_rate", "rate", "ratio", "accuracy", "win_rate", "pct")
WORTH_KEYS = ("n_independent", "p_value", "significant", "baseline", "control",
              "noise", "n_effective", "conf", "ci", "tstat", "basis")


def _py(paths):
    for base in paths:
        for p in sorted(base.rglob("*.py")):
            if "__pycache__" not in str(p):
                yield p


def q3_sibling_sentinels() -> list[dict]:
    """Q3, the biggest generator: absence masked by a plausible number.

    Seven defects had this exact shape, and the shape is always the same — the
    pattern lives in N places, someone fixes the one that bit them, and the
    siblings stay. §4A removed `prices.get(k, 0.0)` from the live path in the
    morning; the identical line was still in the shadow path, in the same file,
    eight hours later (§4.49). `vol_daily or 0.02` was fixed for crypto and left
    for equities (§4.51).

    So this does not report single occurrences — a lone fallback is often
    correct. It reports CLUSTERS: the same masking shape in 2+ places, listed
    together, because the question is not "is this wrong" but "did you get all
    of them".
    """
    clusters = collections.defaultdict(list)
    for path in _py(SCAN):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            shape = target = None
            # x.get(key, <number>)
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get" and len(node.args) == 2
                    and isinstance(node.args[1], ast.Constant)
                    and isinstance(node.args[1].value, (int, float))
                    and not isinstance(node.args[1].value, bool)):
                target = ast.unparse(node.func.value)
                shape = f"{target}.get(..., {node.args[1].value!r})"
            # <expr> or <number>
            elif (isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or)
                  and len(node.values) == 2
                  and isinstance(node.values[1], ast.Constant)
                  and isinstance(node.values[1].value, (int, float))
                  and not isinstance(node.values[1].value, bool)):
                target = ast.unparse(node.values[0])
                shape = f"... or {node.values[1].value!r}"
            if not shape:
                continue
            blob = (target or "").lower()
            if not any(w in blob for w in RISKY):
                continue
            key = f"{shape.split('(')[0][:0]}{re.sub(r'[a-z_]+\\.', '', shape)}"
            clusters[key].append(
                {"file": str(path.relative_to(ROOT)), "line": node.lineno,
                 "code": ast.unparse(node)[:90]})
    return [{"pattern": k, "sites": v} for k, v in sorted(
        clusters.items(), key=lambda kv: -len(kv[1])) if len(v) >= 2]


def q12_rates_without_their_worth() -> list[dict]:
    """Q1 + Q2: a rate published without what its sample is worth, or without
    the null it should be read against.

    §4.37 counted one standing view 65 times. §4.47 was 3 days from grading on
    ~4 independent observations. §4.53 reported 7 symbol-days as `n` and it was
    used to argue for a live order. §4.51 reported a 14.4 ratio with no noise
    floor. Same defect, four modules: **a number that only means something
    beside another number, published alone.**
    """
    out = []
    for path in _py(SCAN):
        try:
            src = path.read_text()
            tree = ast.parse(src)
        except (SyntaxError, OSError):
            continue
        # If the MODULE demonstrably knows about overlapping samples, its rate
        # dicts are not the defect — `adviser_gate.py` sets `min_n` "knowing the
        # effective sample is ~1/5 of min_n" and publishes `effective_n_divisor`.
        # Flagging it anyway is how a detector earns being ignored, which is the
        # lesson `brief_node_audit.py` had to learn the same way.
        if any(w in src for w in ("effective_n_divisor", "n_independent",
                                  "n_effective", "HORIZON_DAYS")):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keys = [k.value for k in node.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)]
            if not keys:
                continue
            rates = [k for k in keys if k.lower() in RATE_KEYS]
            if not rates:
                continue
            if any(any(w in k.lower() for w in WORTH_KEYS) for k in keys):
                continue
            out.append({"file": str(path.relative_to(ROOT)), "line": node.lineno,
                        "rate_keys": rates, "all_keys": keys[:10]})
    return out


def q5_tests_that_cannot_fail() -> list[dict]:
    """Q5: a test that passes with the bug put back is not evidence.

    Eight did, this session. Fully automating mutation testing is out of scope
    here, but the cheapest cases are detectable: a test with no assertion at
    all, or one whose every assertion is on a literal constant (`assert True`,
    `assert 2 == 2`) and therefore cannot depend on the code.
    """
    out = []
    for path in sorted(TESTS.glob("test_*.py")):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for fn in ast.walk(tree):
            if not (isinstance(fn, ast.FunctionDef) and fn.name.startswith("test_")):
                continue
            asserts = [n for n in ast.walk(fn) if isinstance(n, ast.Assert)]
            raises = [n for n in ast.walk(fn)
                      if isinstance(n, ast.Raise) or (
                          isinstance(n, ast.Call) and "raises" in ast.unparse(n))]
            if not asserts and not raises:
                out.append({"file": str(path.relative_to(ROOT)), "line": fn.lineno,
                            "test": fn.name, "why": "no assertion at all"})
                continue
            if asserts and all(isinstance(a.test, ast.Constant) for a in asserts):
                out.append({"file": str(path.relative_to(ROOT)), "line": fn.lineno,
                            "test": fn.name, "why": "every assert is on a literal"})
    return out


CHECKS = {
    "siblings": (q3_sibling_sentinels,
                 "Q3  where else does this pattern live?   (7 of 17 defects)"),
    "rates": (q12_rates_without_their_worth,
              "Q1+Q2  what is this sample worth, and vs what?  (6 of 17)"),
    "vacuous": (q5_tests_that_cannot_fail,
                "Q5  has this test ever actually failed?   (8 found by hand)"),
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", choices=sorted(CHECKS), help="run only one")
    ap.add_argument("--quiet", action="store_true", help="counts only")
    ap.add_argument("--max-sites", type=int, default=6, help="sites shown per cluster")
    args = ap.parse_args(argv)

    names = [args.check] if args.check else list(CHECKS)
    total = 0
    for name in names:
        fn, title = CHECKS[name]
        found = fn()
        total += len(found)
        print(f"\n\033[1m{'=' * 74}\n{title}\n{'=' * 74}\033[0m")
        if not found:
            print("  nothing — this question has no obvious answers left here")
            continue
        if args.quiet:
            print(f"  {len(found)} finding(s)")
            continue
        if name == "siblings":
            print(f"  {len(found)} pattern(s) appearing in 2+ places. A lone fallback is\n"
                  f"  often right; the question is whether you got ALL of them.\n")
            for c in found:
                print(f"  \033[1m{c['pattern']}\033[0m  — {len(c['sites'])} sites")
                for st in c["sites"][:args.max_sites]:
                    print(f"      {st['file']}:{st['line']}   {st['code']}")
                if len(c["sites"]) > args.max_sites:
                    print(f"      ... and {len(c['sites']) - args.max_sites} more")
                print()
        elif name == "rates":
            print(f"  {len(found)} rate(s) published with nothing saying what the\n"
                  f"  sample is worth. §4.53 is what this looks like when it reaches\n"
                  f"  a trade decision.\n")
            for r in found:
                print(f"  {r['file']}:{r['line']}   rate={r['rate_keys']}")
                print(f"      keys: {r['all_keys']}")
        else:
            print(f"  {len(found)} test(s) that cannot depend on the code.\n")
            for t in found:
                print(f"  {t['file']}:{t['line']}   {t['test']}  — {t['why']}")

    print(f"\n{'-' * 74}")
    print(f"{total} question(s) worth answering.")
    print("Every line above is a QUESTION, not a verdict. A clean sweep means\n"
          "these four questions have no obvious answers left — not that the\n"
          "code is correct.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
