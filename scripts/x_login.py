#!/usr/bin/env python3
"""One-time interactive X login into a persistent headless profile.

Runs the x.com login flow in data/x_profile (persistent context — the session
survives on disk afterwards, so x_auto_capture.py can reuse it forever).
The flow is driven stepwise: after submitting the email it POLLS
data/x_login_input.txt for whatever X asks next (OTP, password, username),
so the operator can relay values from the account owner mid-flow.

Protocol per step: this script writes the current page's visible text to
data/x_login_page.txt and a screenshot to data/x_login_step.png, then waits
(up to 20 min) for data/x_login_input.txt to appear; consumes it, types it
into the focused input, presses Enter, repeats. Write STOP to abort.
Exits 0 once logged in (home timeline visible).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "data" / "x_profile"
PAGE_TXT = ROOT / "data" / "x_login_page.txt"
SHOT = ROOT / "data" / "x_login_step.png"
INBOX = ROOT / "data" / "x_login_input.txt"

EMAIL = sys.argv[1]


def snapshot(page, note: str) -> None:
    try:
        PAGE_TXT.write_text(f"[{note}]\n" + page.inner_text("body")[:4000])
        page.screenshot(path=str(SHOT))
    except Exception as exc:
        PAGE_TXT.write_text(f"[{note}] snapshot failed: {exc}")
    print(f"step: {note}", flush=True)


def wait_input(timeout_s: int = 1200) -> str | None:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if INBOX.exists():
            v = INBOX.read_text().strip()
            INBOX.unlink()
            return None if v.upper() == "STOP" else v
        time.sleep(3)
    return None


def logged_in(page) -> bool:
    return "home" in page.url and page.locator('[data-testid="primaryColumn"]').count() > 0


def main() -> int:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        ctx = pw.firefox.launch_persistent_context(
            str(PROFILE), headless=True, viewport={"width": 1280, "height": 900})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://x.com/i/flow/login", wait_until="domcontentloaded")
        time.sleep(10)
        snapshot(page, "initial login page")
        def submit(value: str) -> None:
            """Type into the login form's visible input and advance. The
            options screen renders "Email or username" as a button that must
            be clicked before any input exists."""
            sel = ('input[autocomplete="username"], input[name="text"], '
                   'input[type="email"], input[type="text"], input:visible')
            field = page.locator(sel).first
            if not field.is_visible():
                opener = page.get_by_text("Email or username", exact=True).first
                if opener.count():
                    opener.click()
                    time.sleep(3)
                field = page.locator(sel).first
            field.wait_for(state="visible", timeout=30000)
            field.click()
            field.fill("")
            page.keyboard.type(value, delay=90)   # real keystrokes: X's form
            time.sleep(1.5)                       # validation ignores fill()
            clicked = False
            for _ in range(20):   # wait for X's validation to arm the button
                for label in ("Continue", "Next", "Log in"):
                    for b in page.get_by_role("button", name=label, exact=True).all():
                        if not b.is_visible():
                            continue
                        if (b.get_attribute("aria-disabled") or "").lower() == "true" \
                                or b.is_disabled():
                            continue
                        b.click()
                        clicked = True
                        break
                    if clicked:
                        break
                if clicked:
                    break
                time.sleep(0.5)
            if not clicked:
                page.keyboard.press("Enter")
            time.sleep(6)

        submit(EMAIL)

        for step in range(6):
            if logged_in(page):
                snapshot(page, "LOGGED IN")
                print("SUCCESS — session saved in persistent profile", flush=True)
                ctx.close()
                return 0
            snapshot(page, f"awaiting input, step {step}")
            val = wait_input()
            if val is None:
                snapshot(page, "aborted/timeout")
                ctx.close()
                return 3
            submit(val)
        snapshot(page, "too many steps — giving up")
        ctx.close()
        return 3


if __name__ == "__main__":
    sys.exit(main())
