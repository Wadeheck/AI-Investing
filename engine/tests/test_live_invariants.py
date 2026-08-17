"""The invariants the 15-minute watchdog now carries.

Each one is a bug that actually happened on 2026-08-17 and was found by hand,
hours after it started. Hand-inspection does not scale to four books across four
market sessions a day.

A check that cannot fail is decoration, so every test here breaks the invariant
deliberately and asserts the check notices.
"""
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine"))

_spec = importlib.util.spec_from_file_location(
    "daily_status", ROOT / "scripts" / "daily_status.py")
ds = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ds)


def _run(books: dict):
    """Point daily_status at a temp data dir holding `books`, return {key: ok}."""
    tmp = tempfile.mkdtemp()
    for fname, blob in books.items():
        with open(os.path.join(tmp, fname), "w") as fh:
            json.dump(blob, fh)
    orig_D, orig_results = ds.D, list(ds.RESULTS)
    ds.D = lambda *p: os.path.join(tmp, *p)
    ds.RESULTS = []
    try:
        ds.check_shared_account()
        return {r["key"]: r for r in ds.RESULTS}
    finally:
        ds.D, ds.RESULTS = orig_D, orig_results


def _book(marks=None, pending=None, positions=None, base=10_000.0):
    return {"ledger": {"base": base, "realized": 0.0, "adjust": 0.0, "fees": 0.0,
                       "marks": marks or {}},
            "pending": pending or [], "sim_keys": [],
            "broker": {"cash": 0.0, "positions": positions or []}}


def _wrap(book):
    """The two books that nest their ledger under `stock_ledger`."""
    b = dict(book)
    return {"stock_ledger": {k: b[k] for k in ("ledger", "pending", "sim_keys")},
            "broker": b["broker"]}


# ------------------------------------------------------------ cost basis ----
def test_a_cost_basis_in_the_wrong_currency_is_caught():
    """100 shares of 3690.HK filled at HKD 8,870 and went into a USD ledger at
    8,870 — seven times what it cost. Equity read $2,256 against a true
    $10,000 and every downstream number inherited it."""
    bad = _book(positions=[{"symbol": "3690.HK", "avg_price": 88.70, "price": 11.30}])
    r = _run({"live_book.json": bad})["book cost basis scale"]
    assert not r["ok"]
    assert "3690.HK" in r["detail"] and "FX scale" in r["detail"]


def test_an_ordinary_loss_is_not_mistaken_for_an_fx_error():
    """A position down 40% must not page anyone."""
    ok = _book(positions=[{"symbol": "AAPL", "avg_price": 300.0, "price": 180.0}])
    assert _run({"live_book.json": ok})["book cost basis scale"]["ok"]


# ------------------------------------------------------------ commitment ----
def test_a_book_committing_more_than_it_holds_is_caught():
    """The 4.46x runaway: $33,946 of live orders against a $7,612 book."""
    bad = _book(pending=[{"symbol": "NVDA", "side": "buy", "qty": 150, "price": 225.0,
                          "ts": "2026-08-17T00:00:00+00:00"}])
    r = _run({"live_book.json": bad})["book cash commitment"]
    assert not r["ok"] and "committed" in r["detail"]


def test_a_book_within_its_cash_is_fine():
    ok = _book(pending=[{"symbol": "NVDA", "side": "buy", "qty": 10, "price": 225.0,
                         "ts": "2026-08-17T00:00:00+00:00"}])
    assert _run({"live_book.json": ok})["book cash commitment"]["ok"]


# -------------------------------------------------------------- duplicates --
def test_the_same_name_ordered_twice_is_caught():
    """NVDA and AMD were each ordered twice within 45 minutes, because a queued
    order is not a position and the re-entry guards only saw positions."""
    bad = _book(pending=[
        {"symbol": "NVDA", "side": "buy", "qty": 5, "price": 225.0,
         "ts": "2026-08-17T00:00:00+00:00"},
        {"symbol": "NVDA", "side": "buy", "qty": 5, "price": 225.0,
         "ts": "2026-08-17T00:45:00+00:00"}])
    r = _run({"live_book.json": bad})["duplicate venue orders"]
    assert not r["ok"] and "NVDA x2" in r["detail"]


# ------------------------------------------------------------------ stale ---
def test_an_order_stuck_for_days_is_caught():
    """Its cash stays committed until it settles, so a stuck order silently
    shrinks the book that placed it."""
    bad = _book(pending=[{"symbol": "NVDA", "side": "buy", "qty": 1, "price": 225.0,
                          "ts": "2026-08-10T00:00:00+00:00"}])
    r = _run({"live_book.json": bad})["stale venue orders"]
    assert not r["ok"] and "NVDA" in r["detail"]


# ------------------------------------------------- several books at once ----
def test_every_book_is_checked_not_just_the_first():
    """The sleeve was the one that ran away, and it is not the first file."""
    bad = _book(pending=[{"symbol": "GLD", "side": "buy", "qty": 90, "price": 400.0,
                          "ts": "2026-08-17T00:00:00+00:00"}])
    out = _run({"live_book.json": _book(), "event_state.json": _wrap(bad)})
    r = out["book cash commitment"]
    assert not r["ok"] and "event" in r["detail"]


def test_no_books_means_no_opinion():
    """SHARED_STOCK_ACCOUNT off, or books not yet migrated: the checks must be
    silent rather than inventing a green or a red."""
    out = _run({})
    assert "book cash commitment" not in out


# ------------------------------------ a latched fault is announced ONCE -----
def test_an_ongoing_data_fault_is_not_re_announced_after_a_restart():
    """`688836.SS` is Unitree — a STAR Market listing that has not started
    trading, so neither Yahoo nor Longbridge prices it. It has been flagged
    1,094 times, and on 2026-08-17 it paged the user twice in one hour for the
    sole reason that the engine restarted twice: `_flagged_symbols` was
    in-memory, so every boot rediscovered every ongoing fault as new."""
    import json as _json
    from ai_investing.util import atomic

    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "data_guard_flags.json")

    def announce(bad, remembered):
        """The runner's rule: alert only on what CHANGED."""
        return sorted(set(bad) - set(remembered)), sorted(set(remembered) - set(bad))

    bad = {"stock:688836.SS"}
    remembered = set()
    newly, cleared = announce(bad, remembered)
    assert newly, "the first sighting must alert"
    atomic.write_json(path, sorted(bad))

    # the engine restarts, twice
    for _ in range(2):
        with open(path) as fh:
            remembered = set(_json.load(fh))
        newly, cleared = announce(bad, remembered)
        assert not newly and not cleared, \
            "a restart must not turn a latched condition back into an event"

    # and a genuine recovery still speaks
    with open(path) as fh:
        remembered = set(_json.load(fh))
    newly, cleared = announce(set(), remembered)
    assert cleared == ["stock:688836.SS"]


def test_the_stall_remedy_matches_the_engine_that_stalled():
    """The alert said "restart with `make run`" whatever the mode. Under systemd
    that starts a SECOND engine writing the same books — the reason the old
    @reboot cron entry was removed. A remedy that is wrong gets followed."""
    src = (ROOT / "scripts" / "daily_status.py").read_text()
    assert "systemctl --user restart ai-investing" in src
    assert '"engine cycling"' in src, "and it should not still be called paper"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"test_live_invariants: all {len(fns)} passed")
