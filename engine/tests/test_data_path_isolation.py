"""No LIVE-PATH module may reach the data directory behind its caller's back.

§4.21: `crypto_book._hist()` built a path to the repo's real `data/` out of
`__file__` and ignored `settings` entirely. A test that carefully redirected
`state_path` into a temp dir therefore still read the live crypto market, and
`test_bear_exit_liquidates_and_holds_cash` passed or failed depending on the
actual stablecoin supply -- green on the dev box's stale snapshot, red on the
ProDesk's live data, and able to flip on either machine on any day.

The general rule: a component that reads from a path its caller cannot set is
neither testable nor configurable, and those are the same defect.

RESEARCH SCRIPTS ARE EXEMPT. `ai_investing/research/*` are offline tools run by
hand against the one real data directory; there is no caller to configure and
nothing in the trading loop imports them. Narrowing the rule to code that can
run inside a cycle is what keeps it enforceable instead of ignored.
"""
import ast
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PKG = Path(__file__).resolve().parents[1] / "ai_investing"

EXEMPT_DIRS = {"research"}

# The live-path modules that still do this, from the §4.21 sweep. They are
# read-only reference loaders (fundamentals, comps, ownership, estimates,
# calendars, the value scanner) rather than anything that decides a trade, so
# they are recorded in STATE §4A rather than swept in one risky change.
#
# This list may SHRINK, never grow. A new entry means a new module reads data
# its caller cannot redirect -- exactly how §4.21 shipped.
KNOWN = {
    "data/calendar_events.py",
    "data/comps.py",
    "data/estimates.py",
    "data/fundamentals_history.py",
    "data/ownership.py",
    "data/value_scanner.py",
    "scalp/live.py",
}


def _offenders() -> set:
    found = set()
    for path in sorted(PKG.rglob("*.py")):
        rel = path.relative_to(PKG).as_posix()
        if rel.split("/")[0] in EXEMPT_DIRS:
            continue
        src = path.read_text()
        if "__file__" not in src:
            continue
        lines = src.splitlines()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Constant) and node.value == "data":
                window = lines[max(0, node.lineno - 4):node.lineno]
                if any("__file__" in ln for ln in window):
                    found.add(rel)
                    break
    return found


def test_no_new_module_hardcodes_the_data_directory():
    found = _offenders()
    new = found - KNOWN
    assert not new, (
        "these modules build a data path from __file__, so no caller and no test "
        f"can redirect them (§4.21): {sorted(new)}")


def test_the_known_list_is_not_stale():
    """A fixed module must be removed from KNOWN, or the guard rots into a
    list of things nobody checks any more."""
    stale = KNOWN - _offenders()
    assert not stale, f"fixed — delete from KNOWN: {sorted(stale)}"


def test_crypto_book_reads_history_through_settings():
    """The specific regression: the bear signals must follow state_path."""
    import inspect
    from ai_investing.strategy import crypto_book as cb

    sig = inspect.signature(cb._hist)
    assert "settings" in sig.parameters, \
        "_hist must take settings, or tests read the live market again"

    import tempfile
    tmp = tempfile.mkdtemp()

    class S:
        state_path = os.path.join(tmp, "state.json")

    class F:
        settings = S()

    n, why = cb.CryptoBook.bear_evidence(F(), {})
    assert (n, why) == (0, []), \
        f"an isolated data dir must yield no market signal, got {why}"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} data-path isolation tests passed.")
