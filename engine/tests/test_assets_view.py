"""What /assets says must survive the day the feed breaks.

Every failure in this project's register was a confidently-wrong number, and the
balance sheet is the line a person actually glances at. These pin the three ways
it could lie: netting shorts away, rendering cash as equity, and reporting a
position at zero because a bar was missing.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ai_investing.alerts.chat import ChatBot
from ai_investing.models import mark_price


class _Settings:
    """Only what _fmt_assets touches."""
    def __init__(self, d):
        self.state_path = os.path.join(d, "state.json")
        self.starting_cash = 10000.0
        self.invest_starting_cash = 10000.0
        self.alerts = type("A", (), {"telegram_bot_token": "", "telegram_chat_id": ""})()
        self.brain = type("B", (), {"state_path": os.path.join(d, "brain.json"),
                                    "advice_path": os.path.join(d, "advice.json")})()


def _bot(d):
    os.environ["EVENT_START_CASH"] = "10000"
    os.environ["CRYPTO_START_CASH"] = "10000"
    return ChatBot(_Settings(d))


def _write(d, name, blob):
    with open(os.path.join(d, name), "w") as fh:
        json.dump(blob, fh)


def _long_short_book(equity):
    """$10k book: $5,000 long and $4,000 short, netting to only $1,000."""
    return {"equity": equity,
            "broker": {"cash": 9000.0, "positions": [
                {"symbol": "PDD", "qty": 50.0, "avg_price": 100.0, "price": 100.0},
                {"symbol": "TSLA", "qty": -20.0, "avg_price": 200.0, "price": 200.0}]}}


def test_exposure_is_gross_not_net_when_the_book_is_short():
    """`equity - cash` nets a short against a long and understates the risk.
    The investing book showed $2,094 invested while carrying $9,718 gross."""
    with tempfile.TemporaryDirectory() as d:
        _write(d, "invest_state.json", _long_short_book(10000.0))
        out = _bot(d)._fmt_assets()
        assert "$5,000 long" in out and "$4,000 short" in out, out
        assert "$9,000 at risk" in out, out           # gross, not the $1,000 net
        assert "$1,000 at risk" not in out, out


def test_a_book_that_cannot_be_valued_is_never_shown_as_its_cash():
    """equity == cash with positions open is the §4.7 phantom signature. The
    breaker refuses to act on an unreadable equity; the display must not print
    it as fact either."""
    with tempfile.TemporaryDirectory() as d:
        blob = _long_short_book(10000.0)
        del blob["equity"]
        blob["broker"].pop("equity", None)
        _write(d, "invest_state.json", blob)
        out = _bot(d)._fmt_assets()
        assert "value unknown" in out, out
        assert "NOT counted" in out, out
        assert "incomplete" in out, out
        # the phantom number itself must appear nowhere as this book's equity
        assert "*$9,000*" not in out, out


def test_the_total_says_so_when_a_book_is_missing_from_it():
    """§4.4: $103,333 of capital simply absent from the view, silently."""
    with tempfile.TemporaryDirectory() as d:
        _write(d, "state.json", {"equity": 10000.0, "cash": 10000.0, "positions": []})
        blob = _long_short_book(10000.0)
        del blob["equity"]
        _write(d, "invest_state.json", blob)
        out = _bot(d)._fmt_assets()
        assert "incomplete" in out and "since the" not in out, out


def test_the_two_equity_books_do_not_share_an_icon():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "state.json", {"equity": 1.0, "cash": 1.0, "positions": []})
        _write(d, "event_state.json", {"equity": 1.0, "broker": {"cash": 1.0, "positions": []}})
        out = _bot(d)._fmt_assets()
        assert "📈 trading" in out, out
        assert out.count("⚡") == 1, "trading and the sleeve both rendered as ⚡"


def test_a_zero_price_never_reads_as_a_worthless_position():
    """The runner writes a missing bar as prices[k] = 0.0 (§4A). A plain
    dict-default lets that through as a real price; mark_price is what contains
    it, and both the snapshot and the log line must use it."""
    assert mark_price(0.0, 306.94) == 306.94          # present-but-zero -> cost
    assert mark_price(None, 306.94) == 306.94         # missing -> cost
    assert mark_price(float("nan"), 306.94) == 306.94  # NaN defeats every < guard
    assert mark_price(-5.0, 306.94) == 306.94
    assert mark_price(310.0, 306.94) == 310.0         # a real price is honoured
    # and the staleness probe used by the snapshot agrees
    assert not (mark_price(0.0, 0.0) > 0.0)
    assert mark_price(310.0, 0.0) > 0.0


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} assets-view tests passed.")
