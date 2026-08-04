"""Telegram alerts over the Bot API (stdlib urllib — no SDK).

Setup: talk to @BotFather to create a bot -> TELEGRAM_BOT_TOKEN. Send your bot a
message, then read the chat id from
https://api.telegram.org/bot<token>/getUpdates -> TELEGRAM_CHAT_ID.
Without both, alerts silently no-op (NullNotifier).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod


class Notifier(ABC):
    enabled: bool = False

    @abstractmethod
    def send(self, text: str, buttons=None) -> bool:
        ...


class NullNotifier(Notifier):
    enabled = False

    def send(self, text: str, buttons=None) -> bool:  # no-op
        return False


class TelegramNotifier(Notifier):
    # LAST-DITCH DUPLICATE SUPPRESSION.
    #
    # Four separate announce-the-state bugs reached the user in one day: the circuit
    # breaker every 5 minutes for 9 hours, the data guard every cycle, the engine's
    # own "started" message 18 times during a crash loop, and a news/context error
    # every cycle of a provider outage. Each was fixed at its call site, and a fifth
    # will eventually be written.
    #
    # So the notifier itself now refuses to repeat an IDENTICAL message inside a
    # window. This is deliberately a backstop, not the design: a call site that
    # announces a state is still a bug and still gets fixed. But the user should
    # never again receive eighteen copies of anything because one caller forgot.
    #
    # Keyed on exact text, so a message carrying changing detail (a price, a count)
    # still gets through — the storms were all byte-identical.
    DEDUPE_WINDOW_S = 1800.0        # 30 minutes
    DEDUPE_MAX_KEYS = 256           # bounded: this runs for months

    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.enabled = bool(token) and bool(chat_id)
        self._recent: dict[str, float] = {}
        self.suppressed = 0          # counted so the log can admit what it dropped

    def _is_duplicate(self, text: str) -> bool:
        now = time.monotonic()
        # monotonic, not wall clock: a clock adjustment must not unblock a storm
        for k, t in list(self._recent.items()):
            if now - t > self.DEDUPE_WINDOW_S:
                del self._recent[k]
        if text in self._recent:
            self.suppressed += 1
            print(f"  (telegram: suppressed a repeat of an identical message — "
                  f"{self.suppressed} so far. A caller is announcing a STATE; "
                  f"fix it there: {text[:60]}…)")
            return True
        if len(self._recent) >= self.DEDUPE_MAX_KEYS:
            self._recent.pop(min(self._recent, key=self._recent.get), None)
        self._recent[text] = now
        return False

    def send(self, text: str, buttons: list[list[tuple[str, str]]] | None = None) -> bool:
        """buttons: rows of (label, callback_data) — the chat bot process
        handles the resulting taps; this notifier only sends."""
        if not self.enabled:
            return False
        if self._is_duplicate(text):
            return True          # not an error: the message was already delivered
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        params = {
            "chat_id": self.chat_id,
            "text": text[:4000],
            "parse_mode": "Markdown",
            "disable_web_page_preview": "true",
        }
        if buttons:
            params["reply_markup"] = json.dumps({"inline_keyboard": [
                [{"text": lbl, "callback_data": data[:64]} for lbl, data in row]
                for row in buttons]})
        def _post(p: dict) -> bool:
            data = urllib.parse.urlencode(p).encode()
            req = urllib.request.Request(url, data=data, method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200

        # TRANSIENT NETWORK FAILURE, ESPECIALLY AT BOOT (added 2026-08-04).
        # The engine's "started" alert is the FIRST outbound request after a
        # reboot, and DNS/routing routinely lag network-online.target by seconds.
        # A single attempt that returns False loses exactly the message that tells
        # you the machine came back — observed on the 21:19 boot, where the two
        # restarts either side both delivered and the boot itself did not.
        #
        # Retried before the Markdown fallback, and separately from it: an HTTP 400
        # is a formatting problem that a retry cannot fix, while a DNS failure is a
        # timing problem that only a retry can.
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                return _post(params)
            except urllib.error.HTTPError as exc:
                last_err = exc
                break            # 4xx is a FORMATTING problem; retrying cannot help
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                # a TIMING problem — DNS not up yet, no route, connection reset.
                # Only a retry can fix this one. Note URLError subclasses OSError,
                # so HTTPError must be caught above or 400s would be retried 3x.
                last_err = exc
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
            except Exception as exc:
                last_err = exc
                break            # unknown cause: do not spin, fall to plain text

        # LAST RESORT, ALWAYS TRIED. Whatever went wrong above, attempt the message
        # once more without Markdown before giving up.
        #
        # Telegram 400s on unbalanced Markdown, and this system's alert text is FULL
        # of underscores — node ids (geopolitical_tension), file paths
        # (proposal_log.jsonl), scoring labels — each of which reads as an italic
        # marker. Returning False here once silently DROPPED the alert: a notifier
        # that loses the message it was built to deliver is the worst failure in
        # this codebase, because every other safeguard reports through it.
        # Ugly beats undelivered.
        try:
            plain = dict(params)
            plain["parse_mode"] = ""
            return _post(plain)
        except Exception as exc:
            # NEVER SILENT. The absence of an alert must not be indistinguishable
            # from the absence of a problem.
            err = last_err or exc
            print(f"  !! telegram send FAILED, message not delivered "
                  f"({type(err).__name__}: {err}): {text[:90]}")
            return False
