"""The 2026-08-05 storm: 15 pages in 90 minutes for a condition that was
neither changing nor real.

Three independent failures lined up, and each gets its own tests here:

  1. The watchdog's 6-hour rate limit keyed on the rendered sentence, which
     carried a live token count -- so no two runs looked like the same issue.
  2. The notifier's backstop keyed on exact text, and the storm was not
     byte-identical, so it passed all 15 through.
  3. The condition was false anyway: end-of-day use was extrapolated linearly
     from midnight, which reads the nightly digest burst as a runaway.

Each of the three alone would have produced the storm. That is why they are
tested separately rather than through one end-to-end case.
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from ai_investing.alerts.telegram import TelegramNotifier   # noqa: E402


class _Spy(TelegramNotifier):
    """Counts what would actually leave the machine."""

    def __init__(self):
        super().__init__("t", "c")
        self.sent = []

    def send(self, text, buttons=None):
        if self._too_noisy(text):
            return True
        self.sent.append(text)
        return True


def _storm_line(tokens, pct):
    """A real line from the storm, with its numbers as they actually ticked."""
    return (f"🚨 *AI-Investing needs attention*\n"
            f"• LLM free allowance: vgxfw={tokens}k({pct}%) of 5M/day each "
            f"— busiest projects to 262% by day end")


# --------------------------------------------------------------- notifier ---

def test_the_actual_storm_is_suppressed():
    n = _Spy()
    for tok, pct in [(1011, 20.2), (1041, 20.8), (1069, 21.4), (1100, 22.0),
                     (1131, 22.6), (1178, 23.6), (1198, 24.0), (1223, 24.5)]:
        with contextlib.redirect_stdout(io.StringIO()):
            n.send(_storm_line(tok, pct))
    assert len(n.sent) == TelegramNotifier.SHAPE_ALLOWANCE, \
        f"the storm got through again: {len(n.sent)} of 8 delivered"
    assert n.suppressed == 5


def test_exact_repeats_are_suppressed_immediately():
    n = _Spy()
    with contextlib.redirect_stdout(io.StringIO()):
        for _ in range(5):
            n.send("engine started")
    assert n.sent == ["engine started"]


def test_genuinely_different_alerts_all_get_through():
    """The suppression must not become the place real alerts go to die."""
    n = _Spy()
    n.send("Bought 10 AAPL @ 150.10")
    n.send("Bought 4 MSFT @ 300.20")
    n.send("Sold 2 NVDA @ 900.00")
    n.send("circuit breaker tripped")
    assert len(n.sent) == 4, "a real alert was swallowed"


def test_same_symbol_different_fills_still_get_through():
    """Two fills of one name differ ONLY in their numbers -- exactly the case
    the shape key could wrongly collapse. Under the allowance they survive."""
    n = _Spy()
    n.send("Bought 10 AAPL @ 150.10")
    n.send("Bought 12 AAPL @ 150.40")
    assert len(n.sent) == 2


def test_shape_ignores_numbers_but_not_letters():
    s = TelegramNotifier._shape
    assert s("vgxfw=1011k(20.2%)") == s("vgxfw=1041k(20.8%)")
    assert s("AAPL @ 1") != s("MSFT @ 1")


def test_window_expiry_allows_the_alert_to_return():
    """A condition still broken tomorrow must be able to page again."""
    import ai_investing.alerts.telegram as tg
    n = _Spy()
    clock = [1000.0]
    real = tg.time.monotonic
    tg.time.monotonic = lambda: clock[0]
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            for _ in range(6):
                n.send(_storm_line(1, 1.0))
            assert len(n.sent) == 1              # byte-identical after the first
            clock[0] += TelegramNotifier.DEDUPE_WINDOW_S + 1
            n.send(_storm_line(1, 1.0))
    finally:
        tg.time.monotonic = real
    assert len(n.sent) == 2, "suppression must expire, or a real outage goes quiet"


def test_suppression_is_never_silent():
    n = _Spy()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        n.send("x")
        n.send("x")
    assert "suppressed" in buf.getvalue()


# --------------------------------------------------------------- watchdog ---

def _watchdog():
    import importlib
    return importlib.import_module("watchdog")


class _Patch:
    """Minimal monkeypatch: this project's suites run without pytest."""

    def __init__(self):
        self._undo = []

    def attr(self, obj, name, value):
        self._undo.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def undo(self):
        for obj, name, old in reversed(self._undo):
            setattr(obj, name, old)
        self._undo = []


def _wd_harness(p, wd, tmp, health):
    sent = []

    class N:
        def send(self, text, buttons=None):
            sent.append(text)
            return True

    import ai_investing.alerts as al
    import ai_investing.config as cfg
    p.attr(wd, "STATE", Path(tmp) / "state.json")
    p.attr(wd, "check_disk", lambda: [])
    p.attr(al, "get_notifier", lambda s: N())
    p.attr(cfg, "Settings", lambda: object())
    p.attr(wd, "check_health", health)
    return sent


def test_watchdog_keys_on_identity_not_wording():
    """The regression itself: the same issue worded with a new number must NOT
    re-alert inside the 6-hour window."""
    wd, p, tmp = _watchdog(), _Patch(), tempfile.mkdtemp()
    counter = [1011]

    def health():
        counter[0] += 30
        return [("check:LLM free allowance",
                 f"LLM free allowance: vgxfw={counter[0]}k(20.2%)")]

    sent = _wd_harness(p, wd, tmp, health)
    p.attr(wd, "check_services", lambda: [])
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            for _ in range(8):
                wd.main()
    finally:
        p.undo()
    assert len(sent) == 1, \
        f"rate limit keyed on wording again: {len(sent)} alerts for one issue"


def test_watchdog_alerts_on_a_genuinely_new_issue():
    wd, p, tmp = _watchdog(), _Patch(), tempfile.mkdtemp()
    sent = _wd_harness(p, wd, tmp, lambda: [])
    issues = [("service:ai-investing", "service ai-investing is failed")]
    p.attr(wd, "check_services", lambda: list(issues))
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            wd.main()
            issues.append(("disk", "disk 4% free"))
            wd.main()
    finally:
        p.undo()
    assert len(sent) == 2, "a new, different issue must still page"


def test_every_check_returns_keyed_pairs():
    """Structural: a check that returns bare strings reintroduces the bug."""
    import inspect
    wd = _watchdog()
    for fn in (wd.check_services, wd.check_disk, wd.check_health):
        ann = str(inspect.signature(fn).return_annotation)
        assert "tuple" in ann, \
            f"{fn.__name__} must return (key, detail) pairs, not sentences"


# ------------------------------------------------------------- projection ---

def _daily_status():
    import importlib
    return importlib.import_module("daily_status")


def test_burst_at_midnight_does_not_project_a_runaway():
    """The false alarm. 1.37M tokens spent by the nightly crons before 02:00,
    then a trickle: the day ends near half the cap, not at 262%."""
    ds, p = _daily_status(), _Patch()
    usage = {
        "day": "2026-08-05",
        "by_model": {"vgxfw": 1_370_000},
        # the burst landed in hours 0-1; hours 2-5 are the live loop's trickle
        "by_hour": {"vgxfw": {"0": 700_000, "1": 311_000, "2": 90_000,
                              "3": 90_000, "4": 90_000, "5": 89_000}},
    }
    p.attr(ds, "NOW", datetime(2026, 8, 5, 5, 3, tzinfo=timezone.utc))
    try:
        proj, basis = ds._project_eod(usage, 5_000_000)
    finally:
        p.undo()
    assert proj < 100, f"still cries wolf: {proj:.0f}%"
    assert 30 < proj < 90, f"and must stay honest, not merely quiet: {proj:.0f}%"
    assert "rate" in basis


def test_a_real_runaway_still_alerts():
    """The check must keep its teeth: sustained heavy burn projects over."""
    ds, p = _daily_status(), _Patch()
    usage = {
        "day": "2026-08-05",
        "by_model": {"vgxfw": 1_500_000},
        "by_hour": {"vgxfw": {str(h): 300_000 for h in range(5)}},
    }
    p.attr(ds, "NOW", datetime(2026, 8, 5, 5, 0, tzinfo=timezone.utc))
    try:
        proj, _ = ds._project_eod(usage, 5_000_000)
    finally:
        p.undo()
    assert proj > 100, f"a genuine overrun must page: {proj:.0f}%"


def test_falls_back_when_no_hourly_history():
    """Files written by the older build carry no by_hour; must not crash."""
    ds, p = _daily_status(), _Patch()
    usage = {"day": "2026-08-05", "by_model": {"vgxfw": 1_000_000}}
    p.attr(ds, "NOW", datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc))
    try:
        proj, basis = ds._project_eod(usage, 5_000_000)
    finally:
        p.undo()
    assert abs(proj - 40.0) < 1.0, proj
    assert basis == "elapsed-rate"


def test_no_paging_on_the_discredited_estimator():
    """The elapsed-rate fallback is the estimator that produced the storm. It
    may still report a number; it must not be allowed to page.

    Checked by CALLING the gate rather than grepping this file for a literal —
    the previous version asserted on source text and broke on a refactor that
    strengthened the very guarantee it was protecting (2026-08-16)."""
    import daily_status as ds

    # every discredited basis is barred, with a reason to show the reader
    assert ds._why_not_paging("elapsed-rate")
    assert ds._why_not_paging("too few complete hours")
    # ...and a basis measured from real complete hours is allowed through
    assert ds._why_not_paging("last 4h rate, burst hour dropped") is None

    # the gate is actually wired into the row, not merely defined
    block = (ROOT / "scripts" / "daily_status.py").read_text().split(
        "--- LLM free-allowance budget ---")[1]
    assert "_why_not_paging(basis)" in block, "the allowance row must consult the gate"


def test_cap_comes_from_settings_not_a_copy():
    """daily_status hardcoded 5_000_000 while the engine read the env var, so
    setting LLM_DAILY_FREE_TOKENS would have moved one and not the other."""
    src = (ROOT / "scripts" / "daily_status.py").read_text()
    # code only -- a comment mentioning the old literal is not a regression
    code = [ln.split("#")[0] for ln in src.splitlines()]
    assigns = [ln for ln in code if "cap" in ln and "=" in ln and "_get" not in ln]
    assert any("_free_token_cap()" in ln for ln in assigns), \
        "the allowance check must read the cap from Settings"
    assert not any("cap = 5_000_000" in ln for ln in assigns), \
        "the cap must not be a second copy of the engine's setting"


def test_json_mode_emits_only_json():
    """The watchdog parses stdout; a line of prose there breaks every check."""
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "daily_status.py"),
                        "--json"], capture_output=True, text=True, timeout=600,
                       cwd=str(ROOT))
    rows = json.loads(r.stdout)          # raises if prose leaked into stdout
    assert isinstance(rows, list) and rows, "no checks reported"
    assert all({"key", "ok", "detail"} <= set(row) for row in rows)


def test_usage_meter_records_hours():
    """The projection needs hourly buckets; the meter must write them."""
    from ai_investing.data import news
    tmp = tempfile.mkdtemp()

    class S:
        state_path = os.path.join(tmp, "state.json")

    news._record_usage(S(), "vgxfw", 1234)
    news._record_usage(S(), "vgxfw", 1000)
    with open(news._usage_path(S())) as fh:
        data = json.load(fh)
    hh = str(datetime.now(timezone.utc).hour)
    assert data["by_model"]["vgxfw"] == 2234
    assert data["by_hour"]["vgxfw"][hh] == 2234


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} alert-storm tests passed.")
