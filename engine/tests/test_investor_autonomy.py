"""The 🏛 investing book must honour TRADE_APPROVAL.

It had no such check: it executed ONLY on a proposal the user had tapped
`approved`. So when TRADE_APPROVAL was set to false, three books went autonomous
and this one silently kept waiting for taps that were never coming — unable to
open a position, while still asking permission on Telegram. See STATE §4.17.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_investing.config import Settings
from ai_investing.strategy.investor import Investor


class Recorder:
    """Stands in for the notifier and records what the user would have received."""
    enabled = True

    def __init__(self):
        self.msgs: list[str] = []
        self.buttons = 0

    def send(self, text, buttons=None):
        self.msgs.append(text)
        if buttons:
            self.buttons += 1
        return True


def _investor(tmp, approval: bool):
    s = Settings()
    s.state_path = os.path.join(tmp, "state.json")
    s.proposals_path = os.path.join(tmp, "proposals.jsonl")
    s.trade_approval = approval
    s.invest_starting_cash = 10_000.0
    return Investor(s)


_STRAT = {"theses": [{"title": "semis cycle turning", "stance": "long",
                      "symbols": ["AAA"], "why": "x", "assumptions": "y"}]}
_PRICES = {"AAA": 100.0}


def test_with_approval_off_it_buys_without_asking():
    with tempfile.TemporaryDirectory() as tmp:
        inv = _investor(tmp, approval=False)
        n = Recorder()
        inv.daily_manage(_PRICES, _STRAT, n, {"AAA": "Alpha"})

        held = inv.broker.get_positions()
        assert held, f"the book must OPEN the position itself; messages={n.msgs}"
        assert n.buttons == 0, "an autonomous book must not send approval buttons"
        assert any("Bought" in m for m in n.msgs), \
            f"the fill must still be reported: {n.msgs}"
        assert not any("approval needed" in m for m in n.msgs)


def test_with_approval_on_it_still_asks_first():
    with tempfile.TemporaryDirectory() as tmp:
        inv = _investor(tmp, approval=True)
        n = Recorder()
        inv.daily_manage(_PRICES, _STRAT, n, {"AAA": "Alpha"})

        assert not inv.broker.get_positions(), \
            "with approval ON nothing may be opened unasked"
        assert n.buttons >= 1 and any("approval needed" in m for m in n.msgs)


def test_the_cash_reserve_holds_on_both_paths():
    """The reserve rule was duplicated in the approved path and would have been
    duplicated again for the autonomous one. Both now go through _open, because
    duplicated rules drift — that is exactly how the sleeve's entry and exit paths
    disagreed about symbol keys for the life of the project."""
    with tempfile.TemporaryDirectory() as tmp:
        inv = _investor(tmp, approval=False)
        # spend the pot down so the reserve binds
        inv.broker._cash = 1_000.0
        n = Recorder()
        inv.daily_manage(_PRICES, _STRAT, n, {"AAA": "Alpha"})
        assert not inv.broker.get_positions(), \
            "a buy that breaches the dry-powder reserve must be skipped, not forced"
        assert any("cash reserve floor" in m for m in n.msgs), \
            f"and the skip must be explained: {n.msgs}"


def _journal(inv) -> list[dict]:
    import json
    try:
        return [json.loads(l) for l in open(inv.journal) if l.strip()]
    except OSError:
        return []


def test_every_entry_is_journalled():
    """This book was the only one of the four writing no trade record at all.
    The cost surfaced on 2026-08-10 as a realised -$11.32 that reconciled
    arithmetically and could not be attributed to any trade, because no exit had
    ever been recorded anywhere. Equity was right; it was simply unauditable."""
    with tempfile.TemporaryDirectory() as tmp:
        inv = _investor(tmp, approval=False)
        inv.daily_manage(_PRICES, _STRAT, Recorder(), {"AAA": "Alpha"})
        rows = [r for r in _journal(inv) if r["event"] in ("buy", "short")]
        assert len(rows) == 1, f"the open left no record: {_journal(inv)}"
        r = rows[0]
        assert r["symbol"] == "AAA" and r["price"] == 100.0
        assert r["qty"] > 0 and r["notional"] > 0
        assert r["ts"] and r["thesis"] == "semis cycle turning"


def test_every_exit_is_journalled_with_its_entry_and_pnl():
    """An exit must record what it sold, at what price, against what entry —
    the three numbers needed to reconstruct a realised P&L later."""
    with tempfile.TemporaryDirectory() as tmp:
        inv = _investor(tmp, approval=False)
        inv.daily_manage(_PRICES, _STRAT, Recorder(), {"AAA": "Alpha"})
        # next day, thesis gone: the position must be closed and recorded
        inv._state["last_managed"] = "1970-01-01"
        inv.daily_manage({"AAA": 110.0}, {"theses": []}, Recorder(), {"AAA": "Alpha"})
        sells = [r for r in _journal(inv) if r["event"] == "sell"]
        assert len(sells) == 1, f"the exit left no record: {_journal(inv)}"
        s = sells[0]
        assert s["entry"] == 100.0 and s["price"] == 110.0
        assert s["qty"] > 0 and s["pnl"] > 0 and s["reason"]
        # and the book is genuinely flat, so the record matches reality
        assert not inv.broker.get_positions()


def test_a_refused_entry_is_recorded_too():
    """The dry-powder floor and the broker's insufficient-cash path both refuse
    silently. 'Why did it not take that thesis' has no answer without a line."""
    with tempfile.TemporaryDirectory() as tmp:
        inv = _investor(tmp, approval=False)
        inv.broker._cash = 1_000.0
        inv.daily_manage(_PRICES, _STRAT, Recorder(), {"AAA": "Alpha"})
        rej = [r for r in _journal(inv) if r["event"] == "rejected"]
        assert len(rej) == 1 and rej[0]["symbol"] == "AAA", _journal(inv)
        assert rej[0]["reason"], "a refusal without a reason is not a record"


def test_the_daily_equity_line_is_written_once_per_day():
    """Marking runs every cycle (~288/day); logging each would bury the trades
    the file exists to hold."""
    with tempfile.TemporaryDirectory() as tmp:
        inv = _investor(tmp, approval=False)
        for _ in range(5):
            inv.mark(_PRICES)
        marks = [r for r in _journal(inv) if r["event"] == "mark"]
        assert len(marks) == 1, f"expected one mark/day, got {len(marks)}"
        assert marks[0]["equity"] is not None and "cash" in marks[0]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} investor-autonomy tests passed.")
