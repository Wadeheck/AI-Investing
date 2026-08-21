"""The shared-account drift latch: halt on disagreement, resume when it settles.

§4.35. `_reconcile_shared()` sets `_shared_drift` when the books' claims and the
account disagree, and `_reconcile()` refuses to trade while it is set. That is
correct and must stay correct — trading on a wrong picture of who owns what is
exactly what it prevents.

What was wrong: the latch was cleared ONLY by an operator restart, on the
reasoning that "a disagreement about who owns which shares does not resolve
itself". Mostly true, but the commonest cause is a pending order caught
mid-settlement, and `resolve_pending()` fixes precisely that within the same or
the very next cycle. On 2026-08-19 a late USO fill halted all four books for
~40 minutes for a condition that had already cleared.

Three properties, and the third is the one that makes the fix safe to ship:
  1. a drift that has settled lets the engine resume, by itself;
  2. a drift that is real keeps it halted, indefinitely;
  3. the re-check never re-alerts — re-announcing one condition every cycle is
     §4.20, fifteen pages in ninety minutes.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class _Journal:
    def __init__(self):
        self.events = []

    def record_event(self, kind, detail):
        self.events.append((kind, detail))


class _Notifier:
    def __init__(self):
        self.sent = []

    def send(self, msg):
        self.sent.append(msg)


class _Runner:
    """Only the collaborators `_reconcile`'s latch block actually touches."""

    from ai_investing.runner import Runner as _R
    _reconcile = _R._reconcile

    def __init__(self, drift_sequence):
        # each call to _reconcile_shared pops the next verdict
        self._verdicts = list(drift_sequence)
        self._shared_drift = "USO: book claims 2, account holds 0"
        self._last_positions = None
        self.journal = _Journal()
        self.notifier = _Notifier()
        self.shared_calls = []
        self.book = None

    def _reconcile_shared(self, quiet=False):
        self.shared_calls.append(quiet)
        ok = self._verdicts.pop(0)
        if not ok:
            self._shared_drift = "USO: book claims 2, account holds 0"
            if not quiet:
                self.journal.record_event("shared_claim_drift", "…")
                self.notifier.send("⚠️ SHARED ACCOUNT DRIFT")
        return ok


class _Portfolio:
    positions: dict = {}


def test_a_drift_that_settles_lets_the_engine_resume():
    r = _Runner([True])                       # re-check: the claim has settled
    assert r._reconcile(_Portfolio()) is True, "a settled drift must not keep halting"
    assert r._shared_drift is None
    assert [k for k, _ in r.journal.events] == ["shared_claim_drift_cleared"], \
        "the resumption is recorded, not silent"


def test_a_real_drift_keeps_the_engine_halted():
    r = _Runner([False])                      # re-check: still disagreeing
    assert r._reconcile(_Portfolio()) is False
    assert r._shared_drift, "the latch must be re-armed, not dropped"


def test_a_real_drift_stays_halted_cycle_after_cycle():
    """The property that matters most: no timeout, no retry budget. A drift that
    never clears never resumes."""
    r = _Runner([False] * 25)
    for _ in range(25):
        assert r._reconcile(_Portfolio()) is False
    assert r._shared_drift


def test_the_re_check_never_re_alerts():
    """§4.20. One condition, one page. The re-check is `quiet`, so a book halted
    for an hour does not send ten identical warnings."""
    r = _Runner([False] * 12)
    for _ in range(12):
        r._reconcile(_Portfolio())
    assert r.shared_calls == [True] * 12, "every re-check must be quiet"
    assert r.notifier.sent == [], "a re-check must never re-alert"
    assert r.journal.events == [], "nor re-journal the same drift"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} shared-drift-latch tests passed.")
