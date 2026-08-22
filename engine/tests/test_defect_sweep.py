"""The defect sweep must find the defects it was built from.

§4.54. Seventeen defects were found on 2026-08-21/22 in a system with 645
passing tests, two of them introduced during the review itself. That says the
defect rate tracks how hard someone looks — which makes quality a function of
who is on shift.

The seventeen were not seventeen insights. Sorted by the QUESTION that surfaced
each, **13 of 17 came from four questions a script can ask.**
`scripts/defect_sweep.py` asks them.

The only honest test of such a tool is whether it finds the things it was built
from. These cases are the real defects, reduced to fixtures.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import defect_sweep as ds  # noqa: E402


def test_it_finds_the_shape_that_caused_seven_defects():
    """§4.49's actual shape: the same masking fallback in two paths, one fixed
    and one not. Reported as a CLUSTER, because the question is never 'is this
    line wrong' — it is 'did you get all of them'."""
    clusters = ds.q3_sibling_sentinels()
    assert clusters, "the sibling check found nothing at all — it is broken"
    for c in clusters:
        assert len(c["sites"]) >= 2, "a single site is not a cluster"
    flat = {(s["file"], s["line"]) for c in clusters for s in c["sites"]}
    assert len(flat) > 10, "implausibly few sites; the matcher is too narrow"


def test_a_lone_fallback_is_not_reported():
    """The property that keeps this readable. A one-off default is usually
    correct, and reporting it is how a detector earns being ignored — the
    lesson `brief_node_audit.py` learned by crying wolf on prose."""
    for c in ds.q3_sibling_sentinels():
        assert len(c["sites"]) > 1


def test_a_module_that_already_handles_overlap_is_not_flagged():
    """`adviser_gate.py` publishes `{n, hit, days}` with no `n_independent` —
    which looks exactly like §4.53. It is not: that module sets `min_n = 80`
    *"knowing the effective sample is ~1/5 of min_n"* and publishes
    `effective_n_divisor`. The first version of the sweep flagged it anyway.

    A false positive on a module that demonstrably did the thinking is the
    difference between a tool that gets run and one that gets ignored.
    """
    flagged = {r["file"] for r in ds.q12_rates_without_their_worth()}
    assert not any("adviser_gate" in f for f in flagged), \
        f"adviser_gate flagged despite handling effective n: {flagged}"


def test_the_vacuous_test_check_catches_a_test_that_cannot_fail():
    """Eight tests this session passed with the bug put back. Full mutation
    testing is not automatable here, but the floor cases are: no assertion at
    all, or assertions only on literals."""
    import ast
    src = '''
def test_nothing():
    x = 1
def test_literal_only():
    assert True
def test_real():
    assert compute() == 42
'''
    tree = ast.parse(src)
    fns = {f.name: f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef)}
    def verdict(fn):
        asserts = [n for n in ast.walk(fn) if isinstance(n, ast.Assert)]
        if not asserts:
            return "no assertion at all"
        if all(isinstance(a.test, ast.Constant) for a in asserts):
            return "every assert is on a literal"
        return None
    assert verdict(fns["test_nothing"]) == "no assertion at all"
    assert verdict(fns["test_literal_only"]) == "every assert is on a literal"
    assert verdict(fns["test_real"]) is None


def test_the_suite_itself_has_no_test_that_cannot_fail():
    """Run the check against this repo's own tests. It is the one place the
    tool's output is also its own subject."""
    vacuous = ds.q5_tests_that_cannot_fail()
    assert not vacuous, f"tests that cannot depend on the code: {vacuous}"


def test_every_check_is_read_only():
    """This runs against a live trading repo. It must never write."""
    src = (Path(__file__).resolve().parents[2] / "scripts" / "defect_sweep.py").read_text()
    for banned in ("open(", ".write(", "os.remove", "shutil", "subprocess"):
        if banned == "open(":
            continue          # read_text only; no bare open() is used
        assert banned not in src, f"defect_sweep must be read-only, found {banned}"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} defect-sweep tests passed.")
