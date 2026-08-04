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


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} investor-autonomy tests passed.")
