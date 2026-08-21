#!/usr/bin/env python3
"""Unattended X (Twitter) harvest — the browser-capture protocol, minus the human.

Automates docs/data-pipeline/X_BROWSER_CAPTURE.md with headless Playwright and
the user's saved X session. Same hard rules as the manual protocol: read-only,
one browser, one profile at a time, human pacing, stop on any challenge
interstitial. Output goes through scripts/x_capture_ingest.py (imported, not
reimplemented) so the dedup contract and ad-filtering stay in one place.

Setup (one-time): put the logged-in session cookies in data/x_cookies.json,
chmod 600, shaped {"auth_token": "...", "ct0": "..."} — from the user's
Chrome: x.com > DevTools > Application > Cookies. Sessions last months;
when it expires this script exits 3 and needs_you nags for fresh cookies.

Usage: x_auto_capture.py [--days N] [--feed-only]
Exit codes: 0 harvested, 2 nothing new, 3 not logged in / challenged.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

COOKIES = ROOT / "data" / "x_cookies.json"

# §1 tier profiles, priority order. The Following feed is captured first and
# catches anything the user follows beyond this list.
PROFILES = ["FarsideUK", "glassnode", "WuBlockchain", "TheBlockCo", "Blockworks",
            "MessariCrypto", "coinbureau", "EleanorTerrett", "zachxbt",
            "WatcherGuru", "brian_armstrong", "cz_binance", "scottmelker",
            "RaoulGMI", "Rager", "MacroCRG", "benjamincowen", "PlanB"]

HARVEST_JS = """
() => {
  const out = [];
  document.querySelectorAll('article').forEach(a => { try {
    const tl = a.querySelector('a[href*="/status/"] time'); if (!tl) return;
    const u = tl.closest('a').getAttribute('href');
    const t = tl.getAttribute('datetime');
    const txt = a.querySelector('[data-testid="tweetText"]');
    out.push({u, t, x: txt ? txt.innerText.replace(/\\n+/g, ' ').slice(0, 400) : ''});
  } catch (e) {} });
  return out;
}
"""

CHALLENGE_MARKERS = ("unusual activity", "verify", "rate limit exceeded",
                     "something went wrong. try reloading")


def _pause(lo: float = 0.7, hi: float = 1.3) -> None:
    time.sleep(random.uniform(lo, hi))


def drain(page, cutoff_ms: int, cap: dict, max_steps: int = 120) -> None:
    """§2: small scroll steps, human pacing, stop when the feed runs dry."""
    dry = 0
    for _ in range(max_steps):
        for r in page.evaluate(HARVEST_JS):
            try:
                ts = time.mktime(time.strptime(r["t"][:19], "%Y-%m-%dT%H:%M:%S")) * 1000
            except ValueError:
                continue
            if ts < cutoff_ms or r["u"] in cap:
                continue
            cap[r["u"]] = r
            dry = -1          # found something new this step
        dry += 1
        if dry >= 8:
            return
        page.mouse.wheel(0, random.randint(500, 900))
        _pause()


def run(days: int, feed_only: bool) -> int:
    try:
        ck = json.loads(COOKIES.read_text())
        assert ck.get("auth_token") and ck.get("ct0")
    except (OSError, ValueError, AssertionError):
        print(f"no session: put auth_token+ct0 in {COOKIES} (chmod 600)")
        return 3

    from playwright.sync_api import sync_playwright
    cutoff_ms = (time.time() - days * 86400) * 1000
    cap: dict[str, dict] = {}
    with sync_playwright() as pw:
        # X_CAPTURE_BROWSER=firefox|chromium — both are Playwright's own bundled
        # builds (~/.cache/ms-playwright), not the system browsers.
        engine = os.environ.get("X_CAPTURE_BROWSER", "chromium")
        browser = getattr(pw, engine).launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"))
        ctx.add_cookies([
            {"name": "auth_token", "value": ck["auth_token"],
             "domain": ".x.com", "path": "/", "httpOnly": True, "secure": True},
            {"name": "ct0", "value": ck["ct0"],
             "domain": ".x.com", "path": "/", "secure": True}])
        page = ctx.new_page()

        targets = ["https://x.com/home"] + \
                  ([] if feed_only else [f"https://x.com/{h}" for h in PROFILES])
        for url in targets:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(random.uniform(2.5, 4.0))
            body = (page.inner_text("body", timeout=10000) or "").lower()
            if "log in" in body and "article" not in page.content():
                print("not logged in — session cookies expired")
                browser.close()
                return 3
            if any(m in body for m in CHALLENGE_MARKERS):
                print(f"challenge interstitial at {url} — ending session (hard rule 3)")
                break
            before = len(cap)
            drain(page, cutoff_ms, cap)
            print(f"{url}: +{len(cap) - before} posts", flush=True)
            time.sleep(random.uniform(4, 9))   # between profiles: reading, not crawling
        browser.close()

    if not cap:
        print("nothing harvested")
        return 2
    # Hand off to the canonical ingester — dedup, ad filter, day-record schema.
    import subprocess
    rows = list(cap.values())
    tmp = ROOT / "data" / "x_auto_harvest.json"
    tmp.write_text(json.dumps(rows))
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "x_capture_ingest.py"),
                        str(tmp), "--note", f"auto headless session, {days}d window"])
    print(f"harvested {len(rows)} rows this session")
    return r.returncode


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--feed-only", action="store_true")
    a = ap.parse_args(argv)
    return run(a.days, a.feed_only)


if __name__ == "__main__":
    raise SystemExit(main())
