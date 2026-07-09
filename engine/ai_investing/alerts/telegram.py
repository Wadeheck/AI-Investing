"""Telegram alerts over the Bot API (stdlib urllib — no SDK).

Setup: talk to @BotFather to create a bot -> TELEGRAM_BOT_TOKEN. Send your bot a
message, then read the chat id from
https://api.telegram.org/bot<token>/getUpdates -> TELEGRAM_CHAT_ID.
Without both, alerts silently no-op (NullNotifier).
"""
from __future__ import annotations

import urllib.parse
import urllib.request
from abc import ABC, abstractmethod


class Notifier(ABC):
    enabled: bool = False

    @abstractmethod
    def send(self, text: str) -> bool:
        ...


class NullNotifier(Notifier):
    enabled = False

    def send(self, text: str) -> bool:  # no-op
        return False


class TelegramNotifier(Notifier):
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.enabled = bool(token) and bool(chat_id)

    def send(self, text: str) -> bool:
        if not self.enabled:
            return False
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": self.chat_id,
            "text": text[:4000],
            "parse_mode": "Markdown",
            "disable_web_page_preview": "true",
        }).encode()
        try:
            req = urllib.request.Request(url, data=data, method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except Exception:
            return False
