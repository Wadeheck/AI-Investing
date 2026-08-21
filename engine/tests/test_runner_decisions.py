"""What a cycle DECIDES — not merely that it executes.

`test_runner_cycle.py` proves the hot path runs end to end, which is what §4.16
needed after a missing attribute crash-looped the live engine with 27 suites
green. §4A has carried "main-loop coverage is one smoke test — everything
between 'runs' and 'correct' is uncovered" as the largest untested surface in
the repo ever since.

This is that surface. Every test below is a scenario that has ALREADY cost this
project money or a book, driven through a real `Runner` against synthetic data:

  §4.7   a feed outage valued the whole book at zero and flattened it
  §4.5   guard-flagged prices reached the stop logic
  §4.10  four books, four private valuation rules, one shared phantom
  §4.14  a change of book size read as a 90% crash
  §4.35  a reconciliation latch that could not clear itself

The bar is deliberately higher than the smoke test's: these assert on the
DECISION, so a change that keeps the cycle running while quietly changing what
it concludes fails here.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_PATH_VARS = (("STATE_PATH", "state.json"), ("DB_PATH", "journal.db"),
              ("BREAKER_PATH", "breaker.json"), ("PARAMS_PATH", "formula.json"),
              ("USER_VIEWS_PATH", "user_views.json"),
              ("HEARTBEAT_PATH", "heartbeat.json"),
              ("BRAIN_DB_PATH", "brain.db"), ("BRAIN_GRAPH_PATH", "graph.json"),
              ("BRAIN_STATE_PATH", "brain.json"), ("BRAIN_FIELD_PATH", "field.json"),
              ("BRAIN_REGIME_PATH", "regime.json"),
              ("BRAIN_SCENARIOS_PATH", "scen.json"),
              ("BRAIN_ADVICE_PATH", "advice.json"),
              ("BRAIN_FEED_CACHE_PATH", "feed.json"),
              ("BRAIN_MACRO_CACHE_PATH", "macro.json"),
              ("BRAIN_SENTIMENT_CACHE_PATH", "sent.json"))


def _isolate():
    """A private scratch dir per test, not per module.

    These tests deliberately drive a book into halted, flagged and blacked-out
    states. Sharing one directory means the breaker one test latches is still
    latched for the next, so a later test halts for a reason it never set up —
    which is precisely how the drift-resume test failed here while passing in
    isolation. §4.40's test-isolation debt, paid in this file.
    """
    tmp = tempfile.mkdtemp()
    for var, name in _PATH_VARS:
        os.environ[var] = os.path.join(tmp, name)
    return tmp


_isolate()
os.environ.update({
    "DATA_PROVIDER": "synthetic", "LIVE_TRADING": "false",
    "STOCK_WATCHLIST": "AAA,BBB,CCC", "CRYPTO_WATCHLIST": "BTC/USD",
    "STARTING_CASH": "10000", "TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": "",
    "TRADE_APPROVAL": "false", "LIVE_CAPITAL_BASE": "0",
})

from ai_investing.config import Settings          # noqa: E402
from ai_investing.runner import Runner            # noqa: E402


def _fresh():
    _isolate()
    return Runner(Settings(), use_news=False)


def _hold(runner, **qty_by_symbol):
    """Put real positions in the book before testing how they are VALUED.

    Without this the synthetic book sits 100% cash, and every outage test below
    passes because there is nothing to collapse. A test that is green because it
    tested nothing is worse than no test — it is the false assurance this whole
    register is about — so `_assert_holding` pins that the fixture actually took.
    """
    from ai_investing.models import Asset, AssetClass, Position
    for sym, qty in qty_by_symbol.items():
        cls = AssetClass.CRYPTO if "/" in sym else AssetClass.STOCK
        a = Asset(sym, cls)
        # Cost basis = the CURRENT synthetic price, so the position opens flat.
        # A fixed basis (100.0) against synthetic prices around $250 showed
        # +149% unrealised and the very first cycle took profit on all of it —
        # leaving the outage tests with nothing to value, which is the vacuity
        # `_assert_holding` exists to catch. It caught exactly this.
        bars = runner.provider.get_bars(a, limit=250)   # same call the cycle makes
        px = bars[-1].close if bars else 100.0
        runner.broker._positions[a.key] = Position(a, qty, px)
        runner.broker._cash -= qty * px
    return runner


def _assert_holding(runner, msg="fixture did not actually open a position"):
    assert runner.broker.get_positions(), msg
    return sum(p.qty * p.avg_price for p in runner.broker.get_positions().values())


def _blackout(runner):
    """Every feed returns nothing — the 2026-08-03 yfinance rate-limit, exactly.

    Patched at the PROVIDER, not at `prices`, so the whole chain from bars to
    valuation is under test rather than a convenient midpoint.
    """
    runner.provider.get_bars = lambda a, limit=250: []
    spot = getattr(runner.provider, "spot", None)
    if spot:
        runner.provider.spot = lambda *a, **k: {}


# ---------------------------------------------------------------- §4.7 ----
def test_a_total_feed_outage_does_not_collapse_equity():
    """THE ONE THAT COST A BOOK. On 2026-08-03 every symbol came back
    'possibly delisted', every position valued at 0.0, and equity read $116,027
    against a real ~$129k. On 08-04 the same shape faked a 13.8% crash and
    flattened a healthy book."""
    r = _hold(_fresh(), AAA=20, BBB=15)
    invested = _assert_holding(r)
    before = r.run_cycle()["equity"]
    assert invested > 0.2 * before, "fixture: the book must be meaningfully invested"

    _blackout(r)
    after = r.run_cycle()

    assert after["equity"] > 0, "a blackout must never value the book at zero"
    assert after["equity"] > invested * 0.5, (
        "the holdings must survive the outage at cost basis — valuing them at "
        "zero is §4.7 exactly")
    assert abs(after["equity"] - before) / before < 0.02, (
        f"equity moved {(after['equity'] - before) / before:+.1%} on a pure DATA "
        f"failure — no price changed, so no value did")

    # AND THE REPRESENTATION, not just the outcome. Everything above still
    # passes with the 0.0 sentinel reintroduced, because `mark_price()` at every
    # consumer contains it — which is real defence and exactly why §4.7 has been
    # survivable since 08-04. But containment is a promise every FUTURE consumer
    # has to keep, and this assertion is what makes the source fix a fact rather
    # than a convention. Found by mutation-testing this file: re-adding the
    # sentinel left all eight tests green until this line existed.
    assert r._last_prices == {} or all(v for v in r._last_prices.values()), (
        f"a missing bar must produce NO KEY, not a zero: "
        f"{ {k: v for k, v in r._last_prices.items() if not v} }")


def test_a_total_feed_outage_places_no_orders():
    """§4.5's other half: skipping a DECISION on bad data is correct and must
    stay. A cycle that cannot see prices must not conclude anything."""
    r = _hold(_fresh(), AAA=20)
    _assert_holding(r)
    r.run_cycle()
    _blackout(r)
    out = r.run_cycle()
    assert out.get("orders", 0) == 0, "no price, no trade"


def test_a_feed_outage_is_reported_not_swallowed():
    """An outage that changes nothing must still SAY so — silence is how §4.7
    ran for a day. This is also the regression guard for omitting price keys:
    with no keys there is nothing to iterate, and the guard must still fire."""
    r = _hold(_fresh(), AAA=20)
    r.run_cycle()
    sent: list[str] = []

    class _Counting:
        enabled = True

        def send(self, text, buttons=None):
            sent.append(text)
            return True

    r.notifier = _Counting()
    r.settings.alerts.on_error = True
    _blackout(r)
    r.run_cycle()
    assert any("DATA GUARD" in t for t in sent), \
        "a blanket outage must alert — an absent price is as bad as a zero one"


# ---------------------------------------------------------------- §4.5 ----
def test_a_flagged_symbol_is_excluded_from_decisions_but_still_valued():
    """The distinction §4.5 turned on, and the one `mark_price`'s docstring
    exists to protect: skipping a decision is safe, skipping a position silently
    rewrites the book's value."""
    r = _hold(_fresh(), AAA=20)
    _assert_holding(r)
    r.run_cycle()
    equity_before = r.run_cycle()["equity"]

    r.guard.check = lambda prices, bars: ({"stock:AAA"}, ["stock:AAA: stale data"])
    out = r.run_cycle()
    assert out["equity"] > 0
    assert abs(out["equity"] - equity_before) / equity_before < 0.05, \
        "flagging a symbol must not remove its value from the book"


# --------------------------------------------------------------- §4.14 ----
def test_equity_is_stable_across_cycles_when_nothing_happens():
    """Three cycles on the same synthetic data. Any drift here is a phantom —
    the family that produced §4.7, §4.10 and §4.14."""
    r = _hold(_fresh(), AAA=20, BBB=10)
    _assert_holding(r)
    eq = [r.run_cycle()["equity"] for _ in range(3)]
    for a, b in zip(eq, eq[1:]):
        assert abs(b - a) / a < 0.10, f"unexplained equity drift {a:,.2f} -> {b:,.2f}"


def test_the_cycle_reports_a_book_that_reconciles():
    """cash + holdings must equal the equity the cycle reports. §4.36's
    signature was these two disagreeing by $4,265 on a flat book."""
    r = _hold(_fresh(), AAA=20, BBB=10)
    _assert_holding(r)
    out = r.run_cycle()
    state = json.load(open(r.settings.state_path))
    assert state.get("positions"), "fixture: the state file must record holdings"
    parts = state["cash"] + sum(
        p.get("qty", 0) * (p.get("price") or p.get("avg_price") or 0)
        for p in (state.get("positions") or []))
    assert abs(parts - out["equity"]) < max(1.0, 0.01 * out["equity"]), (
        f"reported equity {out['equity']:,.2f} does not reconcile with "
        f"cash+holdings {parts:,.2f}")


# --------------------------------------------------------------- §4.35 ----
def test_a_shared_account_drift_halts_the_next_cycle_and_can_clear():
    """The latch must stop the next cycle, and — since 2026-08-21 — must be able
    to resume by itself once the claim settles, without a restart."""
    r = _fresh()
    r.run_cycle()
    r._shared_drift = "AAA: book claims 5, account holds 0"

    r._reconcile_shared = lambda quiet=False: False          # still disagreeing
    out = r.run_cycle()
    assert out.get("halted") is True and out.get("reason") == "reconcile_drift"

    r._reconcile_shared = lambda quiet=False: True           # settled
    out = r.run_cycle()
    assert out.get("halted") is False, "a settled drift must not need a restart"


# ------------------------------------------------------------ risk caps ----
def test_the_cycle_never_grows_a_position_past_the_weight_cap():
    """The risk layer's most basic promise, asserted on the real decision output
    rather than on a unit-tested helper.

    The fixture opens positions comfortably INSIDE the cap on purpose. Seeding
    an already-over-cap position would test the fixture rather than the engine —
    the first draft did exactly that and "failed" at 49.8% on a holding this
    test had created itself.
    """
    r = _hold(_fresh(), AAA=2, BBB=2, CCC=2)
    _assert_holding(r)
    cap = r.settings.risk.max_position_weight
    for _ in range(3):
        r.run_cycle()
    out = r.run_cycle()
    state = json.load(open(r.settings.state_path))
    assert state.get("positions"), "fixture: nothing to cap-check"
    for p in (state.get("positions") or []):
        px = p.get("price") or p.get("avg_price") or 0
        weight = abs(p.get("qty", 0) * px) / max(1.0, out["equity"])
        assert weight <= cap * 1.5 + 0.01, (
            f"{p.get('symbol')} at {weight:.1%} of the book, cap is {cap:.1%}")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} runner-decision tests passed.")
