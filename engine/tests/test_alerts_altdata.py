"""Offline tests for alerts + alt-data (no network calls)."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_investing.alerts import get_notifier
from ai_investing.alerts import telegram as _tg_mod
from ai_investing.alerts.telegram import NullNotifier, TelegramNotifier
from ai_investing.config import settings
from ai_investing.data import altdata
from ai_investing.data.altdata import AltSignal, aggregate


def test_null_notifier():
    n = NullNotifier()
    assert n.enabled is False and n.send("x") is False


def test_telegram_disabled_without_creds():
    n = TelegramNotifier("", "")
    assert n.enabled is False and n.send("x") is False


def test_get_notifier_never_raises():
    with patch("ai_investing.alerts.telegram.urllib.request.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.status = 200
        n = get_notifier(settings)
        assert n.send("x") in (True, False)  # must never raise
    if not (settings.alerts.telegram_bot_token and settings.alerts.telegram_chat_id):
        assert isinstance(n, NullNotifier)


def test_options_flow_unconfigured():
    if not settings.altdata.polygon_api_key:          # returns before any network call
        s = altdata.options_flow(settings, "AAPL")
        assert s.available is False and "POLYGON" in s.detail


def test_aggregate_merges_available_only():
    sigs = [
        AltSignal("a", available=True, intensity=0.3, bullish=0.5),
        AltSignal("b", available=True, intensity=0.8, bullish=-0.1),
        AltSignal("c", available=False, intensity=0.9, bullish=1.0),  # ignored
    ]
    agg = aggregate(sigs)
    assert agg["available"] is True
    assert abs(agg["intensity"] - 0.8) < 1e-9      # max of available
    assert abs(agg["bullish"] - 0.2) < 1e-9        # mean of available
    assert aggregate([])["available"] is False


def test_notifier_falls_back_to_plain_text_rather_than_dropping_the_message():
    """Telegram 400s on unbalanced Markdown, and this system's alert text is full
    of underscores: node ids (geopolitical_tension), file paths
    (proposal_log.jsonl), scoring labels (short_or_avoid). The old send()
    returned False and SILENTLY DROPPED the alert -- the worst failure in the
    codebase, because every other safeguard reports through it.
    """
    from ai_investing.alerts.telegram import TelegramNotifier

    n = TelegramNotifier("tok", "chat")
    calls = []

    def fake_post(params):
        calls.append(params.get("parse_mode"))
        if params.get("parse_mode") == "Markdown":
            raise RuntimeError("400 Bad Request: can't parse entities")
        return True

    import urllib.request
    real = urllib.request.urlopen

    class _Resp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=10):
        body = req.data.decode()
        mode = "Markdown" if "parse_mode=Markdown" in body else ""
        calls.append(mode)
        if mode == "Markdown":
            raise RuntimeError("400 can't parse entities")
        return _Resp()

    urllib.request.urlopen = fake_urlopen
    try:
        ok = n.send("geopolitical_tension via proposal_log.jsonl and short_or_avoid")
    finally:
        urllib.request.urlopen = real
    assert ok is True, "an unparseable-markdown alert must still be delivered"
    assert calls == ["Markdown", ""], f"expected a plain-text retry, got {calls}"



def test_a_transient_network_failure_is_retried_then_reported():
    """The boot-time alert is the first outbound request after a reboot, and DNS
    can lag network-online.target. On 2026-08-04 the 21:19 boot delivered no
    "started" message while the restarts either side both did — one attempt, a
    False return, and no trace anywhere.

    A 400 must NOT be retried this way (it is a Markdown problem the plain-text
    fallback handles); a URLError must be.
    """
    import io
    import urllib.error
    import urllib.request
    from ai_investing.alerts.telegram import TelegramNotifier

    n = TelegramNotifier("tok", "42")
    calls = []

    class _Resp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def flaky(req, timeout=None):
        calls.append(req)
        if len(calls) < 3:
            raise urllib.error.URLError("Temporary failure in name resolution")
        return _Resp()

    real_open, real_sleep = urllib.request.urlopen, _tg_mod.time.sleep
    urllib.request.urlopen = flaky
    _tg_mod.time.sleep = lambda s: None          # do not actually wait in a test
    try:
        assert n.send("engine started") is True, "a transient failure must be retried"
        assert len(calls) == 3, f"expected 3 attempts, got {len(calls)}"
        # 2 network failures, then the 3rd attempt succeeded — no plain-text needed

        # total failure: reports False AND says so, rather than vanishing
        calls.clear()
        urllib.request.urlopen = lambda req, timeout=None: (
            calls.append(req) or (_ for _ in ()).throw(
                urllib.error.URLError("no route to host")))
        buf = io.StringIO()
        _stdout = sys.stdout
        sys.stdout = buf
        try:
            got = n.send("engine started")
        finally:
            sys.stdout = _stdout
        assert got is False
        # 3 retries, then one final plain-text attempt before admitting defeat
        assert len(calls) == 4, f"expected 3 retries + 1 plain-text, got {len(calls)}"
        assert "not delivered" in buf.getvalue().lower(), \
            "a lost alert must be visible; silence is indistinguishable from health"

        # an HTTP 400 is a formatting problem — retried as PLAIN TEXT, not 3x
        calls.clear()
        def four_hundred(req, timeout=None):
            calls.append(req)
            if len(calls) == 1:
                raise urllib.error.HTTPError("u", 400, "Bad Request", {}, None)
            return _Resp()
        urllib.request.urlopen = four_hundred
        assert n.send("node_id_with_underscores") is True
        assert len(calls) == 2, f"a 400 must fall straight to plain text, got {len(calls)}"
    finally:
        urllib.request.urlopen = real_open
        _tg_mod.time.sleep = real_sleep


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} alerts/alt-data tests passed.")
