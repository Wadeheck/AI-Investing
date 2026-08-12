"""Transient-network resilience for the first outbound call a process makes.

Both long-running services died on *every* boot with the same shape of failure:
the first outbound call ran before DNS was usable, the exception escaped a
constructor, and systemd restarted the process 20s later.

    engine: longport.OpenApiException: error sending request for url
            (https://openapi.longportapp.com/v1/asset/stock?): client error (Connect)
    chat:   urllib.error.URLError: <urlopen error [Errno -3] Temporary failure
            in name resolution>

The units carried `After=network-online.target`, which looks like the fix and
is not: these run under `systemd --user`, whose manager has no such unit at all
(`systemctl --user show network-online.target` reports `LoadState=not-found`).
The ordering was a silent no-op for as long as it had been there.

Waiting harder would not be a real fix either. DNS blips at any time — this box
reaches the internet over home wifi with Tailscale in the path — and an engine
that dies on one failed lookup is fragile mid-session, not just at boot. So the
fix lives here, in-process: the first call retries transient failures with
bounded exponential backoff, and *only* transient ones.

The line that matters is `is_transient`. A refused connection is worth
retrying; a wrong answer from a server we reached is not. `_assert_expected_channel`
raising "this token maps to a funded account" must still kill the process on the
first try — retrying a safety verdict would turn this module into a way to
launder a refusal into a trade.
"""
from __future__ import annotations

import errno
import socket
import ssl
import time
import urllib.error
from typing import Callable, TypeVar

T = TypeVar("T")

# Errno values that mean "the network was not ready", never "the request was wrong".
_TRANSIENT_ERRNOS = frozenset({
    errno.ECONNREFUSED,   # nothing listening yet
    errno.ECONNRESET,     # peer dropped mid-handshake
    errno.ECONNABORTED,
    errno.EHOSTUNREACH,   # no route yet
    errno.ENETUNREACH,
    errno.ENETDOWN,
    errno.ETIMEDOUT,
    errno.EPIPE,
    errno.EAGAIN,
})

# Third-party SDKs that wrap their transport layer (longport wraps reqwest) raise
# an opaque exception type and put the real cause in the message. Matching on text
# is not something to be proud of, but the alternative is treating every SDK error
# as fatal — which is the bug being fixed. Kept deliberately narrow: each fragment
# names a *transport* failure, so no application-level rejection can match one.
_TRANSIENT_FRAGMENTS = (
    "temporary failure in name resolution",
    "name or service not known",
    "nodename nor servname provided",
    "failed to lookup address",
    "dns error",
    "client error (connect)",
    "connection refused",
    "connection reset",
    "connection aborted",
    "network is unreachable",
    "no route to host",
    "timed out",
    "timeout",
    "handshake",
)


def is_transient(exc: BaseException) -> bool:
    """True when `exc` means "the network was not ready", not "the request was wrong"."""
    # DNS lookup failure — the boot-time case, errno -3 (EAI_NONAME/EAI_AGAIN).
    if isinstance(exc, socket.gaierror):
        return True
    if isinstance(exc, (socket.timeout, TimeoutError, ConnectionError)):
        return True
    # URLError wraps the real cause; ssl.SSLError covers a handshake cut short.
    if isinstance(exc, urllib.error.URLError) and not isinstance(exc, urllib.error.HTTPError):
        reason = getattr(exc, "reason", None)
        return is_transient(reason) if isinstance(reason, BaseException) else True
    if isinstance(exc, ssl.SSLError):
        return True
    # An HTTP response means we reached the server: 5xx/429 are worth another go,
    # 4xx is our own bad request and must not be retried.
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in (429, 500, 502, 503, 504)
    if isinstance(exc, OSError) and exc.errno in _TRANSIENT_ERRNOS:
        return True
    # Opaque SDK wrapper — fall back to its message.
    text = str(exc).lower()
    return any(fragment in text for fragment in _TRANSIENT_FRAGMENTS)


def retry_transient(
    fn: Callable[[], T],
    *,
    what: str,
    attempts: int = 6,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
    log: Callable[[str], None] = print,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call `fn`, retrying only transient network failures with exponential backoff.

    Defaults spend at most ~1 minute (2+4+8+16+30) before giving up and re-raising.
    Giving up is correct: systemd's `Restart=always` is the outer loop, so a genuinely
    long outage becomes a restart every 20s rather than a process hung here forever.

    Anything `is_transient` rejects propagates immediately, unretried and unlogged —
    a configuration error or a safety refusal must still fail on the first attempt.
    """
    delay = base_delay
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            if not is_transient(exc) or attempt == attempts:
                raise
            log(f"  {what}: network not ready ({type(exc).__name__}: {exc}) — "
                f"retry {attempt}/{attempts - 1} in {delay:.0f}s")
            sleep(delay)
            delay = min(delay * 2, max_delay)
    raise AssertionError("unreachable")  # pragma: no cover - loop either returns or raises
