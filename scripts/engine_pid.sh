#!/usr/bin/env bash
# Print the ENGINE loop's pid, or nothing. Excludes the Telegram chat bot
# (same module, different role) and never matches the calling shell — the
# mistake that made "engine running" checks lie on 2026-08-02.
for pid in $(pgrep -f "ai_investing\.main" 2>/dev/null); do
  [ "$pid" = "$$" ] && continue
  cmd=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null) || continue
  case "$cmd" in
    *--chat*) continue ;;
    *bash*|*eval*|*pgrep*) continue ;;
    *ai_investing.main*) echo "$pid"; exit 0 ;;
  esac
done
exit 1
