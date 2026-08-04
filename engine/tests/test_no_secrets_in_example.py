"""`.env.example` is TRACKED IN GIT. Nothing real may live in it.

From the brain commit until 2026-08-05 it carried a genuine Gemini API key AND
secret for the account holding real assets — pushed to the remote and preserved in
git history. It surfaced only because the user questioned an unrelated claim of
mine about a different key (STATE §4.18).

This is the one file in the repo where a leak is invisible: it LOOKS like a
template, so nobody reads the values.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# A value is a placeholder if it says so. Anything else long, opaque and mixed-case
# with digits is treated as real until proven otherwise.
_PLACEHOLDER = ("your", "xxx", "changeme", "placeholder", "example", "<", "...",
                "here", "none", "null", "dummy", "test", "sk-...", "abc")
# settings whose legitimate values look like secrets but are public identifiers
_ALLOW_PREFIXES = ("BYTEPLUS_LLM", "BYTEPLUS_CHAIN", "ANTHROPIC_MODEL",
                   "DEEPSEEK_MODEL", "LOCAL_LLM_URL", "STOCK_WATCHLIST",
                   "CRYPTO_WATCHLIST", "MOOMOO_HOST", "REDDIT_USER_AGENT")


def _suspicious(key: str, value: str) -> bool:
    if not value or len(value) < 20 or " " in value:
        return False
    if any(key.startswith(p) for p in _ALLOW_PREFIXES):
        return False
    if any(t in value.lower() for t in _PLACEHOLDER):
        return False
    if value.startswith(("http://", "https://")):
        return False
    if value.replace(".", "").replace("-", "").isdigit():
        return False
    # opaque: letters AND digits, no spaces — the shape of a token
    return bool(re.search(r"[A-Za-z]", value) and re.search(r"\d", value))


def test_the_example_env_contains_no_real_looking_values():
    path = ROOT / ".env.example"
    if not path.exists():
        return
    offenders = []
    for i, line in enumerate(path.read_text().splitlines(), 1):
        if "=" not in line or line.strip().startswith("#"):
            continue
        k, v = line.split("=", 1)
        v = v.split("#")[0].strip()
        if _suspicious(k.strip(), v):
            offenders.append(f"  line {i}: {k.strip()} = {v[:10]}...({len(v)} chars)")
    assert not offenders, (
        ".env.example is tracked in git — a real value here is published. Replace "
        "with an obvious placeholder:\n" + "\n".join(offenders))


def test_the_check_would_have_caught_the_real_leak():
    """The exact pair that was committed, so the guard is known to work rather than
    merely believed to."""
    assert _suspicious("CRYPTO_API_KEY", "account-IHDc6MzSxZsbnfKhL9sF")
    assert _suspicious("CRYPTO_API_SECRET", "3zUh8KWrZK5yPL9MdKPQ5dcT1Pap")
    # and the placeholders that replaced them must pass
    assert not _suspicious("CRYPTO_API_KEY", "account-YOUR_KEY_HERE")
    assert not _suspicious("CRYPTO_API_SECRET", "YOUR_SECRET_HERE")
    # model ids and URLs are public identifiers, not secrets
    assert not _suspicious("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    assert not _suspicious("LOCAL_LLM_URL", "http://localhost:11434/v1")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} example-env secret tests passed.")
