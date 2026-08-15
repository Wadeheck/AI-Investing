#!/usr/bin/env python3
"""One-shot pull of the external fund's portfolio value (funds.livelyfoodhub.com),
a fund traded manually by a friend, not by this engine. Appends a snapshot to
data/external_assets/friend_fund.json so it can be reported alongside this
engine's own assets. Requires FRIEND_FUND_PIN in the environment; never commit
that value. The site's investor_session cookie only lives 24h (Max-Age=86400),
so we log in fresh every run rather than reusing a stored cookie.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_URL = os.environ.get("FRIEND_FUND_BASE_URL", "https://funds.livelyfoodhub.com")
LOGIN_URL = f"{BASE_URL}/api/auth/investor/login"
PORTFOLIO_URL = f"{BASE_URL}/portfolio"
OUT_PATH = Path(__file__).resolve().parents[1] / "data" / "external_assets" / "friend_fund.json"

# Values are server-rendered as plain text next to their labels, e.g.:
#   ...Current NAV</div>...$11,086.04...
# (the all-caps look on the page is CSS text-transform, not the actual text)
# so we match label -> next dollar amount rather than relying on markup,
# which changes across deploys of the dashboard's Next.js build.
FIELD_PATTERNS = {
    "current_nav": r"Current NAV.{0,300}?\$([\d,]+\.\d{2})",
    "investor_equity": r"Investor Equity.{0,300}?\$([\d,]+\.\d{2})",
    "high_water_mark": r"High-Water Mark.{0,300}?\$([\d,]+\.\d{2})",
}


def login(session: requests.Session, pin: str) -> None:
    resp = session.post(
        LOGIN_URL,
        json={"pin": pin},
        headers={"User-Agent": "Mozilla/5.0 (external-fund-pull)"},
        timeout=15,
    )
    if resp.status_code != 200 or "investor_session" not in session.cookies:
        raise RuntimeError(
            f"login failed (status {resp.status_code}) - PIN may be wrong or endpoint changed"
        )


def fetch_snapshot() -> dict:
    pin = os.environ.get("FRIEND_FUND_PIN")
    if not pin:
        print("FRIEND_FUND_PIN not set", file=sys.stderr)
        sys.exit(1)

    session = requests.Session()
    login(session, pin)

    resp = session.get(
        PORTFOLIO_URL,
        headers={"User-Agent": "Mozilla/5.0 (external-fund-pull)"},
        timeout=20,
        allow_redirects=False,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"unexpected status {resp.status_code} fetching portfolio")

    html = resp.text
    values = {}
    for key, pattern in FIELD_PATTERNS.items():
        m = re.search(pattern, html, re.DOTALL)
        if not m:
            raise RuntimeError(f"could not find {key} in page (dashboard markup may have changed)")
        values[key] = float(m.group(1).replace(",", ""))

    values["pulled_at"] = datetime.now(timezone.utc).isoformat()
    return values


def append_snapshot(snapshot: dict) -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    history = []
    if OUT_PATH.exists():
        history = json.loads(OUT_PATH.read_text())
    history.append(snapshot)
    OUT_PATH.write_text(json.dumps(history, indent=2))


if __name__ == "__main__":
    snap = fetch_snapshot()
    append_snapshot(snap)
    print(f"pulled friend fund snapshot: investor_equity=${snap['investor_equity']:.2f}")
