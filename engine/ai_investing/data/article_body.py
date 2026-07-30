"""Full-article body fetching — headlines say THAT something happened, bodies
say HOW and WHO, which is what the digester's escalation pass, the deals
extractor, and the integrity scanner actually feed on ("economists had
forecast 185,000", "people familiar with the matter", the counterparty names
of a $300bn compute deal).

Extraction: trafilatura when available (handles boilerplate, CJK pages),
with a stdlib fallback (largest <p>-dense block) so the pipeline never
depends on the optional package. Bodies are trimmed to BODY_CHARS — the same
~3k window the digestion brief's escalation pass uses.

Politeness/limits: per-cycle cap, per-fetch timeout, one UA, no retries —
a paywall or a slow site costs one attempt and the headline+summary stand.
"""
from __future__ import annotations

import re
import urllib.request

BODY_CHARS = 3000
FETCH_TIMEOUT = 12
_UA = "Mozilla/5.0 (compatible; ai-investing-research/0.1; personal research)"

_P_BLOCK = re.compile(r"<p[^>]*>(.*?)</p>", re.I | re.S)
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _fallback_extract(html: str) -> str:
    """No-dependency extraction: concatenate <p> blocks, longest run wins."""
    paras = [_WS.sub(" ", _TAGS.sub(" ", p)).strip() for p in _P_BLOCK.findall(html)]
    paras = [p for p in paras if len(p) > 60]           # drop nav/boilerplate crumbs
    return " ".join(paras)


def fetch_body(url: str) -> str:
    """Best-effort article text for one URL; '' on any failure."""
    if not url or not url.startswith("http"):
        return ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            raw = resp.read(1_500_000)
        html = raw.decode("utf-8", errors="replace")
    except Exception:
        return ""
    text = ""
    try:
        import trafilatura
        text = trafilatura.extract(html, include_comments=False,
                                   include_tables=False) or ""
    except Exception:
        pass
    if not text:
        text = _fallback_extract(html)
    return _WS.sub(" ", text).strip()[:BODY_CHARS]


def attach_bodies(headlines: list[dict], limit: int = 60) -> int:
    """Fetch bodies in place for up to `limit` headlines that carry a URL and
    no body yet. Returns how many bodies were attached."""
    import time
    got = 0
    for h in headlines:
        if got >= limit:
            break
        if h.get("body") or not h.get("url"):
            continue
        body = fetch_body(h["url"])
        if body and len(body) > 200:                    # a real article, not a stub
            h["body"] = body
            got += 1
        time.sleep(0.2)                                 # politeness
    return got
