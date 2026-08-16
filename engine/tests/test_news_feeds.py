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



# -- the third death mode: healthy HTTP, frozen content ----------------------

def test_silent_feeds_catches_what_http_cannot():
    """A feed can return 200/304 with valid, parseable RSS whose newest item is
    years old. WSJ's public feeds froze in Jan 2025, xinhuanet's in 2017, and
    both still answer politely — so _feed_is_stale calls them healthy (a 304 IS
    a successful answer). The only signal left is whether new articles actually
    reach the brain."""
    import sqlite3
    import tempfile
    from datetime import datetime, timedelta, timezone
    from ai_investing.data.news import SILENT_FEED_DAYS, silent_feeds

    db = os.path.join(tempfile.mkdtemp(), "brain.db")
    con = sqlite3.connect(db)
    con.execute("create table articles (id integer primary key, title text, "
                "source text, published text, first_seen text, digested int)")
    now = datetime.now(timezone.utc)
    for src, ts in [("live.com", now - timedelta(hours=2)),
                    ("quiet.gov", now - timedelta(days=8)),
                    ("frozen.com", now - timedelta(days=SILENT_FEED_DAYS + 5))]:
        con.execute("insert into articles (title, source, first_seen, digested) "
                    "values (?,?,?,1)", ("t", src, ts.isoformat()))
    con.commit()
    con.close()

    class _Brain:
        db_path = db

    class _Cfg:
        brain = _Brain()
        news_rss = ["https://live.com/feed", "https://quiet.gov/feed",
                    "https://frozen.com/feed", "https://never.com/feed"]

    out = dict(silent_feeds(_Cfg()))
    assert "live.com" not in out
    assert "quiet.gov" not in out, "a merely quiet feed must not be called frozen"
    assert out.get("frozen.com", 0) >= SILENT_FEED_DAYS
    assert out.get("never.com") == -1, "a feed that never delivered must be flagged"


def test_silent_feeds_survives_a_missing_article_store():
    from ai_investing.data.news import silent_feeds

    class _Brain:
        db_path = "/nonexistent/brain.db"

    class _Cfg:
        brain = _Brain()
        news_rss = ["https://x.com/feed"]

    assert silent_feeds(_Cfg()) == []



def test_dead_feeds_ignores_urls_no_longer_configured():
    """The cache is keyed by URL and nothing prunes it, so a feed REMOVED from
    news_rss keeps its last entry forever. Reporting it as dead long after it was
    dealt with is how a health check trains people to ignore it — which is the
    failure this whole check exists to prevent."""
    import json as _json
    import tempfile
    from ai_investing.data.news import STALE_FEED_DAYS, dead_feeds

    tmp = tempfile.mkdtemp()
    old = time.time() - (STALE_FEED_DAYS + 5) * DAY
    with open(os.path.join(tmp, "feed_cache.json"), "w") as fh:
        _json.dump({"https://kept.com/feed":    {"last_ok": old, "status": 403},
                    "https://removed.com/feed": {"last_ok": old, "status": 403}}, fh)

    class _Brain:
        feed_cache_path = os.path.join(tmp, "feed_cache.json")

    class _Cfg:
        news_rss = ["https://kept.com/feed"]      # removed.com is gone from config
        brain = _Brain()

    hosts = [h for h, _s, _d in dead_feeds(_Cfg())]
    assert hosts == ["kept.com"], hosts


if __name__ == "__main__":
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("ok")
