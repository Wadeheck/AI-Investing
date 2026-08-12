"""Tests for ai_investing.net — the transient-network retry around startup probes.

The guarantee under test is two-sided, and the second side is the important one:
transient failures retry, and everything else still dies on the first attempt.
A regression that made this retry *everything* would silently convert the
Longbridge wrong-account refusal into a delayed refusal, which is not a refusal.
"""
import errno
import socket
import ssl
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_investing.net import is_transient, retry_transient


def _quiet(_msg):
    pass


def _recorder():
    """A sleep stand-in that records delays instead of spending them."""
    slept = []
    return slept, slept.append


def test_dns_failure_is_transient():
    # The exact boot-time failure: errno -3, "Temporary failure in name resolution".
    assert is_transient(socket.gaierror(-3, "Temporary failure in name resolution"))
    assert is_transient(urllib.error.URLError(
        socket.gaierror(-3, "Temporary failure in name resolution")))


def test_connection_and_timeout_failures_are_transient():
    assert is_transient(ConnectionRefusedError())
    assert is_transient(ConnectionResetError())
    assert is_transient(TimeoutError())
    assert is_transient(socket.timeout())
    assert is_transient(ssl.SSLError("handshake failure"))
    assert is_transient(OSError(errno.ENETUNREACH, "Network is unreachable"))


def test_longport_sdk_wrapper_is_transient():
    # longport raises its own opaque type with the transport error in the message.
    class OpenApiException(Exception):
        pass

    exc = OpenApiException(
        "OpenApiException: error sending request for url "
        "(https://openapi.longportapp.com/v1/asset/stock?): client error (Connect)")
    assert is_transient(exc)


def test_safety_refusal_is_not_transient():
    # THE load-bearing assertion. _assert_expected_channel raises this when the
    # token maps to an unexpected (e.g. funded) account. It must never be retried
    # or softened — a delayed refusal is still a refusal, but a swallowed one
    # routes real orders to the wrong account.
    refusal = RuntimeError(
        "Longbridge token maps to account channel(s) ['lb_live'], but "
        "LONGPORT_EXPECT_CHANNEL='lb_papertrading'. Refusing to trade")
    assert not is_transient(refusal)

    calls = []

    def boom():
        calls.append(1)
        raise refusal

    try:
        retry_transient(boom, what="probe", log=_quiet, sleep=lambda _d: None)
        raise AssertionError("the refusal was swallowed")
    except RuntimeError:
        pass
    assert len(calls) == 1, f"a safety refusal was retried {len(calls)} times"


def test_config_errors_are_not_transient():
    assert not is_transient(KeyError("LONGPORT_APP_KEY"))
    assert not is_transient(ValueError("bad token"))
    # 4xx means we reached the server and asked wrongly; 5xx/429 are worth a retry.
    def http(code):
        return urllib.error.HTTPError("http://x", code, "msg", {}, None)
    assert not is_transient(http(401))
    assert not is_transient(http(404))
    assert is_transient(http(503))
    assert is_transient(http(429))


def test_retries_then_succeeds_with_backoff():
    slept, sleeper = _recorder()
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise socket.gaierror(-3, "Temporary failure in name resolution")
        return "connected"

    out = retry_transient(flaky, what="probe", log=_quiet, sleep=sleeper)
    assert out == "connected"
    assert len(attempts) == 3
    assert slept == [2.0, 4.0], f"expected exponential backoff, got {slept}"


def test_gives_up_after_budget_and_reraises():
    # Giving up is correct: systemd's Restart=always is the outer loop. What must
    # not happen is hanging here forever, or exiting without the original cause.
    slept, sleeper = _recorder()
    attempts = []

    def always_down():
        attempts.append(1)
        raise socket.gaierror(-3, "Temporary failure in name resolution")

    try:
        retry_transient(always_down, what="probe", log=_quiet, sleep=sleeper)
        raise AssertionError("a permanent outage should still raise")
    except socket.gaierror:
        pass
    assert len(attempts) == 6, f"expected 6 attempts, got {len(attempts)}"
    assert slept == [2.0, 4.0, 8.0, 16.0, 30.0], f"backoff should cap at 30s, got {slept}"


def test_startup_probes_are_actually_wired():
    # Both crash sites must keep using the retry. If someone refactors either
    # constructor and drops it, every boot goes back to failing once and the
    # 20s restart gap comes back silently.
    import inspect

    from ai_investing.alerts import chat as chat_mod
    from ai_investing.brokers import live as live_mod

    broker_src = inspect.getsource(live_mod.LongbridgeBroker._assert_expected_channel)
    assert "retry_transient" in broker_src, \
        "the Longbridge channel check no longer retries — boot races return"
    assert "self.ctx.stock_positions" in broker_src, \
        "the channel check no longer probes stock_positions"

    chat_src = inspect.getsource(chat_mod.ChatBot.run_forever)
    assert "retry_transient" in chat_src, \
        "the Telegram getMe handshake no longer retries — boot races return"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} net-retry tests passed.")
