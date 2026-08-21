"""One place that answers "where is the data directory".

§4.21, and §4A's "7 live-path loaders hardcode `data/`".

THE DEFECT, precisely. These loaders all take `settings` and use it correctly
when they get one. The problem is what they did when they did NOT:

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))
    return os.path.join(root, "data", "earnings_calendar.json")

That fallback walks up from the module's own location to the repo's REAL data
directory. So a caller that forgets to pass `settings` — or a test that
carefully redirects `STATE_PATH` into a temp dir and then calls a helper that
takes no settings — silently reads live production data instead of failing.

That is exactly how §4.21 shipped: `crypto_book._hist()` built its path from
`__file__`, so `test_bear_exit_liquidates_and_holds_cash` read the machine's
real crypto history and passed or failed depending on the actual stablecoin
supply — green on the dev box, red on the ProDesk, able to flip on either on
any day.

THE FIX is not "always require settings" — several of these are legitimately
called from scripts and notebooks with nothing to pass. It is to make the
FALLBACK configurable too. `Settings()` is a plain env-driven dataclass with no
side effects, so deriving the default from `Settings().state_path` means the
same `STATE_PATH` environment variable that redirects everything else redirects
these as well. A test that sets it once is now actually isolated.

`__file__` disappears from the chain entirely, which is what the guard in
`tests/test_data_path_isolation.py` checks for.
"""
from __future__ import annotations

import os

_cached: str | None = None


def data_dir(settings=None) -> str:
    """The directory holding this run's JSON caches and databases.

    With `settings`, it is wherever `state_path` lives — unchanged behaviour.
    Without, it is derived from the environment (`STATE_PATH`, honoured by
    `Settings`), never from where this file happens to sit on disk.
    """
    if settings is not None:
        return os.path.dirname(os.path.abspath(settings.state_path))
    return _default_dir()


def _default_dir() -> str:
    """Cached because a loader called per-symbol would otherwise rebuild
    `Settings` in a loop. Cheap either way, but this is a hot-ish path."""
    global _cached
    if _cached is None:
        # Imported here, not at module scope: `config` imports nothing from
        # `data`, and keeping it that way avoids a cycle if that ever changes.
        from ai_investing.config import Settings
        _cached = os.path.dirname(os.path.abspath(Settings().state_path))
    return _cached


def reset_cache() -> None:
    """Forget the derived default — for tests that change `STATE_PATH` after
    something has already asked. Production never needs this."""
    global _cached
    _cached = None


def data_path(name: str, settings=None) -> str:
    """`data_dir()` joined with a filename, which is what every caller wants."""
    return os.path.join(data_dir(settings), name)
