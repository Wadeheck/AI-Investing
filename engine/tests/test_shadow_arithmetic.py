"""The A/B shadow book's arithmetic, and the NaN that outlived every restart.

§4A: *"`shadow.json` held `NaN` cash. Retired in the reset, so it rebuilds
clean — but nothing prevents it recurring, and no test covers the shadow book's
arithmetic."* The row's own cue said the test must be written **before** the
baseline is reactivated, not after.

WHAT MAKES NaN DIFFERENT from ordinary corruption, and why it survived so long:

  1. `NaN` and `Infinity` are NOT valid JSON. Python's encoder emits them
     anyway and its decoder reads them back, so the value ROUND-TRIPS. Once one
     entered the file it came back on every restart, forever.
  2. NaN compares false to everything. `if cash < 0: halt` does not fire.
     `max(0, cash)` returns NaN. Every guard written to catch a bad number
     passes it through, because a guard is a comparison.

So the corruption was permanent AND silent, which is the worst pair. Three
layers now stand between a bad number and that outcome, and each is tested
here on its own, because any one of them alone would have prevented the
incident and all three would have to fail to repeat it:

  WRITE   `atomic.write_json(allow_nan=False)` refuses to serialise it, and
          because serialisation happens before the file is touched, the
          previous good state stays on disk.
  READ    `atomic.read_json` refuses the three non-finite tokens, so a file
          written by an older build cannot re-admit the value the writer now
          refuses to create.
  SOURCE  `_shadow_fill` drops an order with no usable price instead of
          filling it at 0.0 — the same sentinel removed from the live path in
          §4A and left here, which is the §4.14/§4.23/§4.36 pattern of fixing a
          defect where it was observed and nowhere else.
"""
import json
import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_investing.util import atomic  # noqa: E402


def _tmp(name="state.json"):
    return str(Path(tempfile.mkdtemp()) / name)


# --- WRITE ------------------------------------------------------------------

def test_a_non_finite_value_is_refused_before_the_file_is_touched():
    """The property that matters is not merely 'it raises'. It is that the
    PREVIOUS GOOD STATE is still there afterwards — a book that refuses to
    save a corrupt figure but destroys the last good one has not helped."""
    path = _tmp()
    atomic.write_json(path, {"cash": 10_000.0, "positions": []})

    for bad in (float("nan"), float("inf"), float("-inf")):
        try:
            atomic.write_json(path, {"cash": bad, "positions": []})
            raise AssertionError(f"write_json accepted {bad!r}")
        except ValueError:
            pass
        survived = json.loads(Path(path).read_text())
        assert survived["cash"] == 10_000.0, \
            f"writing {bad!r} destroyed the last good state: {survived}"


def test_a_non_finite_value_nested_deep_is_still_refused():
    """State files are trees, not flat maps. A NaN three levels down in a
    position's cost basis is the realistic shape of this bug, not a top-level
    `cash` key."""
    path = _tmp()
    deep = {"book": {"positions": [{"symbol": "AAPL", "avg_price": float("nan")}]}}
    try:
        atomic.write_json(path, deep)
        raise AssertionError("a nested NaN was written")
    except ValueError:
        pass
    assert not Path(path).exists(), "the target was created despite the refusal"


def test_ordinary_values_still_write_normally():
    """A guard that also blocks legitimate writes is a worse defect than the
    one it prevents — the lesson §4.48 cost a data channel to learn."""
    path = _tmp()
    obj = {"cash": 4999.89, "zero": 0.0, "neg": -12.5, "big": 1e300, "none": None}
    atomic.write_json(path, obj)
    assert json.loads(Path(path).read_text()) == obj


# --- READ -------------------------------------------------------------------

def test_a_file_already_holding_nan_is_refused_not_inherited():
    """The fix at the writer does nothing for the file already on disk. This
    is the layer that actually ends the incident: the value that outlived
    every restart no longer survives one."""
    path = _tmp()
    Path(path).write_text('{"cash": NaN, "positions": []}')
    # plain json.load is happy with it — that is the whole problem
    assert math.isnan(json.loads(Path(path).read_text())["cash"])
    assert atomic.read_json(path, default="rebuild") == "rebuild", \
        "read_json inherited a NaN instead of rebuilding"


def test_infinity_in_both_signs_is_refused_too():
    for token in ("Infinity", "-Infinity"):
        path = _tmp()
        Path(path).write_text('{"cash": %s}' % token)
        assert atomic.read_json(path, default="rebuild") == "rebuild", \
            f"read_json accepted {token}"


def test_a_healthy_file_still_reads():
    path = _tmp()
    atomic.write_json(path, {"cash": 10_000.0})
    assert atomic.read_json(path) == {"cash": 10_000.0}


# --- SOURCE -----------------------------------------------------------------

def test_the_shadow_fill_refuses_to_price_an_order_it_has_no_price_for():
    """`_shadow_fill` used `prices.get(key, 0.0)`. A 0.0 mid is not a price,
    it is the absence of one wearing a number's clothes — and it feeds
    straight into the cash arithmetic.

    Driven through the real method rather than a reimplementation of it, so
    the test cannot pass while the wiring is wrong (§4.44's lesson).
    """
    import ast
    src = Path(__file__).resolve().parents[1] / "ai_investing" / "runner.py"
    tree = ast.parse(src.read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_shadow_fill")

    # no `prices.get(..., 0.0)` anywhere in it
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get" and len(node.args) == 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value == 0.0):
            raise AssertionError(
                "_shadow_fill still defaults a missing price to 0.0 — the "
                "sentinel §4A removed from the live path")

    # and it returns early rather than falling through to submit()
    assert any(isinstance(n, ast.Return) for n in ast.walk(fn)), \
        "_shadow_fill has no early return, so an unpriced order still fills"


def test_the_shadow_book_rebuilds_rather_than_reloading_a_corrupt_cash():
    """The end-to-end statement of the defect: a `shadow.json` holding NaN
    cash must not come back as a live broker carrying it."""
    import ast
    src = Path(__file__).resolve().parents[1] / "ai_investing" / "runner.py"
    tree = ast.parse(src.read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_load_shadow")
    body = ast.unparse(fn)
    assert "json.load(" not in body, \
        "_load_shadow still uses json.load, which accepts NaN"
    assert "read_json" in body, \
        "_load_shadow must read through atomic.read_json, which refuses it"
    assert "cash != cash" in body, \
        "_load_shadow must reject a non-finite cash even if it parses"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} shadow-arithmetic tests passed.")
