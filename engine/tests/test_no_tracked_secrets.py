"""Scan every GIT-TRACKED file for credential-shaped values.

On 2026-08-05 a real Gemini API key and secret were found in `.env.example` —
committed since the brain commit, pushed, and preserved in history. That file was
deleted; this test is the reason it cannot happen in the next one.

I had audited this repo's security the day before and reported it clean. The audit
checked tracked file NAMES for credential-shaped patterns and never the CONTENTS of
the one file designed to look harmless. A scanner would have found it in seconds, so
here is the scanner.

Scope is deliberately *tracked files only*: an untracked secret is a local risk, a
tracked one is published.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Vendor prefixes worth matching outright — these are unambiguous.
_HARD = [
    (re.compile(r"\baccount-[A-Za-z0-9]{16,}\b"), "Gemini account key"),
    (re.compile(r"\bmaster-[A-Za-z0-9]{16,}\b"), "Gemini master key"),
    (re.compile(r"\bsk-(?:ant|proj|live)?-?[A-Za-z0-9_\-]{24,}\b"), "OpenAI/Anthropic key"),
    (re.compile(r"\bghp_[A-Za-z0-9]{30,}\b"), "GitHub token"),
    (re.compile(r"\bAKIA[0-9A-Z]{12,}\b"), "AWS access key"),
    (re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_\-]{30,}\b"), "Telegram bot token"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
    (re.compile(r"\bhk_(?:m_)?eyJ[A-Za-z0-9_\-]{40,}"), "Longport access token"),
]

# Assignments of an opaque value to a credential-looking name.
# `[ \t]*` and NOT `\s*` around the separator: `\s` matches a newline, so an empty
# assignment (`TELEGRAM_BOT_TOKEN=`) swallowed the FOLLOWING line and reported it as
# that variable's value. The value must be on the same line as its name.
_SECRET_NAME = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:SECRET|PASSWORD|TOKEN|APIKEY|API_KEY|ACCESS_KEY|PRIVATE_KEY)"
    r"[A-Z0-9_]*)[ \t]*[=:][ \t]*[\"']?([^\s\"',#]{16,})")
_PLACEHOLDER = ("your", "xxx", "changeme", "placeholder", "example", "<", "...", "here",
                "none", "null", "dummy", "fake", "test", "sample", "redacted", "tok",
                "abc", "f" * 8, "0" * 8)

_SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", "data"}
_SKIP_SUFFIX = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".pdf", ".gz",
                ".zip", ".db", ".lock", ".woff", ".woff2", ".ttf"}


def _tracked_files() -> list[Path]:
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                             capture_output=True, text=True, timeout=60)
    except Exception:
        return []
    files = []
    for rel in out.stdout.split("\0"):
        if not rel:
            continue
        p = ROOT / rel
        if any(part in _SKIP_DIRS for part in p.parts) or p.suffix.lower() in _SKIP_SUFFIX:
            continue
        if p.is_file() and p.stat().st_size < 2_000_000:
            files.append(p)
    return files


def findings() -> list[str]:
    out: list[str] = []
    me = Path(__file__).resolve()
    for path in _tracked_files():
        if path.resolve() == me:
            continue          # this file names the patterns on purpose
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        rel = path.relative_to(ROOT)
        for pat, label in _HARD:
            for m in pat.finditer(text):
                line = text[:m.start()].count("\n") + 1
                out.append(f"  {rel}:{line}  {label}: {m.group(0)[:14]}…")
        for m in _SECRET_NAME.finditer(text):
            name, value = m.group(1), m.group(2)
            if any(t in value.lower() for t in _PLACEHOLDER):
                continue
            if value.startswith(("http://", "https://", "$", "{", "%")):
                continue
            if not (re.search(r"[A-Za-z]", value) and re.search(r"\d", value)):
                continue
            line = text[:m.start()].count("\n") + 1
            out.append(f"  {rel}:{line}  {name} = {value[:10]}…({len(value)} chars)")
    return sorted(set(out))


def test_no_tracked_file_contains_a_credential():
    found = findings()
    assert not found, (
        "credential-shaped value in a TRACKED file — tracked means published:\n"
        + "\n".join(found))


def test_the_scanner_catches_what_actually_leaked():
    """Verified against the real pair, so the guard is known to work rather than
    merely believed to."""
    leaked = ("CRYPTO_API_KEY=account-IHDc6MzSxZsbnfKhL9sF\n"
              "CRYPTO_API_SECRET=3zUh8KWrZK5yPL9MdKPQ5dcT1Pap\n")
    assert _HARD[0][0].search(leaked), "the Gemini account-key pattern must match"
    assert _SECRET_NAME.search(leaked), "the SECRET= assignment must match"

    # and the placeholders that replaced it must NOT trip
    safe = ("CRYPTO_API_KEY=account-YOUR_KEY_HERE\n"
            "CRYPTO_API_SECRET=YOUR_SECRET_HERE\n"
            "TELEGRAM_BOT_TOKEN=\n"
            "ANTHROPIC_MODEL=claude-haiku-4-5-20251001\n")
    for m in _SECRET_NAME.finditer(safe):
        assert any(t in m.group(2).lower() for t in _PLACEHOLDER), \
            f"placeholder wrongly flagged: {m.group(0)}"
    assert not _HARD[0][0].search(safe)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} tracked-secret tests passed.")
