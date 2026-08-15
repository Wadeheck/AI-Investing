"""Per-feed liveness: a dead RSS wire must become visible instead of quietly
replaying its last parse forever.

Two real failures on 2026-08-15 motivate these:
  mining.com  — hard 403 for 14 days, correctly dropped but silently absent.
  36kr.com    — stopped being an RSS feed and started serving an HTML page with
                a 200. The fetch "succeeded", _parse_feed raised, the generic
                except replayed 10-day-old headlines every cycle, and `status`
                still read 200. Nothing anywhere said so.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ai_investing.data.news import STALE_FEED_DAYS, _feed_is_stale  # noqa: E402

DAY = 86400


def test_a_304_counts_as_healthy_not_stale():
    """The regression that makes this measurable at all: a 304 means the server
    CONFIRMED our cache is current. A quiet-but-live wire (federalreserve.gov
    goes days between posts) must not look like a dead one."""
    assert not _feed_is_stale({"last_ok": time.time(), "status": 304})
    assert not _feed_is_stale({"last_ok": time.time() - 6 * DAY, "status": 304})


def test_a_feed_failing_past_the_window_is_stale():
    assert _feed_is_stale({"last_ok": time.time() - (STALE_FEED_DAYS + 1) * DAY,
                           "status": 403})
    assert _feed_is_stale({"last_ok": time.time() - 14 * DAY, "status": "ParseError"})


def test_the_36kr_case_a_200_that_no_longer_parses():
    """The nastiest shape: status looks fine, items look fine, and the feed has
    been dead for a fortnight. Staleness must key on last SUCCESS, never on
    whether there are cached items to serve."""
    entry = {"last_ok": time.time() - 10 * DAY, "status": "ParseError",
             "items": [{"title": "ten days old"}] * 15}
    assert _feed_is_stale(entry), "a feed with cached items still counts as dead"


def test_legacy_entries_fall_back_to_fetched():
    """Cache written before last_ok existed must still be judgeable."""
    assert _feed_is_stale({"fetched": time.time() - 30 * DAY})
    assert not _feed_is_stale({"fetched": time.time()})


def test_a_never_seen_feed_is_not_yet_evidence_of_death():
    """No timestamp at all means newly added, not dead — don't drop it unseen."""
    assert not _feed_is_stale({})


if __name__ == "__main__":
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("ok")
