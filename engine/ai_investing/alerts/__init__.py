from ai_investing.alerts.telegram import NullNotifier, Notifier, TelegramNotifier


def get_notifier(settings) -> Notifier:
    a = settings.alerts
    if a.telegram_bot_token and a.telegram_chat_id:
        return TelegramNotifier(a.telegram_bot_token, a.telegram_chat_id)
    return NullNotifier()


__all__ = ["Notifier", "TelegramNotifier", "NullNotifier", "get_notifier"]
