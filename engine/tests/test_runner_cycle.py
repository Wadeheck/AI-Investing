"""Actually RUN a cycle.

Every other suite tests a component. Nothing constructed a Runner and executed
run_cycle(), which is how `AttributeError: 'Runner' object has no attribute
'_flagged_symbols'` shipped with 27 suites green and crash-looped the live engine
18 times in 13 minutes (STATE §4.16).

The bar here is deliberately low and the value is entirely in the coverage: does
the hot path execute end to end, twice, without raising. Cheap to run, and it
catches the whole class of "shipped a reference to something that does not exist".
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_tmp = tempfile.mkdtemp()
# Point every path at a scratch dir BEFORE importing config, so a test can never
# touch the real books. Synthetic data means no network.
for var, name in (("STATE_PATH", "state.json"), ("DB_PATH", "journal.db"),
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
                  ("BRAIN_SENTIMENT_CACHE_PATH", "sent.json")):
    os.environ[var] = os.path.join(_tmp, name)
os.environ.update({
    "DATA_PROVIDER": "synthetic",       # no network
    "LIVE_TRADING": "false",            # never a real broker from a test
    "STOCK_WATCHLIST": "AAA,BBB,CCC",
    "CRYPTO_WATCHLIST": "BTC/USD",
    "STARTING_CASH": "10000",
    "TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": "",   # NullNotifier
    "TRADE_APPROVAL": "false",
    "LIVE_CAPITAL_BASE": "0",
})

from ai_investing.config import Settings          # noqa: E402
from ai_investing.runner import Runner            # noqa: E402


def test_a_cycle_runs_end_to_end_without_raising():
    r = Runner(Settings(), use_news=False)
    out = r.run_cycle()
    assert isinstance(out, dict) and "equity" in out
    assert out["equity"] > 0, "a fresh paper book must have positive equity"


def test_two_cycles_run__state_carried_between_them():
    """The second cycle is the one that matters. `_flagged_symbols` is written at
    the END of a cycle and read at the START, so a missing initialiser kills cycle
    one while a wrong TYPE would only surface on cycle two."""
    r = Runner(Settings(), use_news=False)
    r.run_cycle()
    assert isinstance(r._flagged_symbols, set), \
        "the guard's previous-flag set must exist and be a set after a cycle"
    out = r.run_cycle()
    assert isinstance(out, dict) and out["equity"] > 0


def test_the_guard_alert_fires_on_change_not_every_cycle():
    """§4.15/11: an ongoing data fault must be announced once. Counted through a
    fake notifier, because the bug was in the alert path, not the guard."""
    r = Runner(Settings(), use_news=False)

    sent: list[str] = []

    class Counting:
        enabled = True
        def send(self, text, buttons=None):
            sent.append(text)
            return True

    r.notifier = Counting()
    r.settings.alerts.on_error = True

    # a symbol goes bad and STAYS bad across three cycles
    real_check = r.guard.check
    r.guard.check = lambda prices, bars: ({"stock:AAA"}, ["stock:AAA: stale data"])
    for _ in range(3):
        r.run_cycle()
    flagged_alerts = [t for t in sent if "DATA GUARD" in t]
    assert len(flagged_alerts) == 1, (
        f"an ongoing fault must alert ONCE, got {len(flagged_alerts)} — this is the "
        f"storm that reached the user at 12:11, 12:19 and 12:24")

    # and recovery is reported
    r.guard.check = real_check
    r.run_cycle()
    assert any("recovered" in t for t in sent), "clearing must be announced too"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} runner-cycle tests passed.")
