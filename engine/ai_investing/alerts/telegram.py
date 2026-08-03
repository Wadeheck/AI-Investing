"""Telegram alerts over the Bot API (stdlib urllib — no SDK).

Setup: talk to @BotFather to create a bot -> TELEGRAM_BOT_TOKEN. Send your bot a
message, then read the chat id from
https://api.telegram.org/bot<token>/getUpdates -> TELEGRAM_CHAT_ID.
Without both, alerts silently no-op (NullNotifier).
"""
from __future__ import annotations

import json
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
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.enabled = bool(token) and bool(chat_id)

    def send(self, text: str, buttons: list[list[tuple[str, str]]] | None = None) -> bool:
        """buttons: rows of (label, callback_data) — the chat bot process
        handles the resulting taps; this notifier only sends."""
        if not self.enabled:
            return False
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

        try:
            return _post(params)
        except Exception:
            # Telegram 400s on unbalanced Markdown, and this system's alert text
            # is FULL of underscores — node ids (geopolitical_tension), file
            # paths (proposal_log.jsonl), scoring labels (short_or_avoid) — each
            # of which reads as an italic marker. Returning False here silently
            # DROPPED the alert: a notifier that loses the message it was built
            # to deliver is the worst possible failure in this codebase, because
            # every other safeguard reports through it. Retry as plain text:
            # ugly beats undelivered.
            try:
                plain = dict(params)
                plain["parse_mode"] = ""
                return _post(plain)
            except Exception:
                return False
