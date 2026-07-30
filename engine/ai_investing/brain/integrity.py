"""Per-asset integrity flags: the Wirecard/FTX/Luckin early-warning layer.

History's lesson: frauds are usually EXPOSED in public long before the final
collapse — short-seller reports (Wirecard 2015-2020, Luckin), auditor
resignations, delayed filings, withdrawal halts (Celsius months before FTX),
"guaranteed return" marketing (every Ponzi ever). Markets ignore these for
months because the numbers still look great — which is exactly why a model
must NOT weigh the numbers once integrity is in doubt.

Mechanism: scan each cycle's headlines for integrity-event patterns, map the
story to a specific asset via the graph's alias index, and keep a DECAYING
flag per asset (half-life ~45 days, refreshed on every new hit, severity
accumulates). Consumers:
  - valuation anchors: a flagged asset gets a standing negative pull that
    OVERRIDES good fundamentals (the books are the thing in question)
  - the adviser refuses fresh longs on flagged assets
Flags persist in data/integrity_flags.json.
"""
from __future__ import annotations

import json
import os
import re
import time

HALF_LIFE_DAYS = 45.0
FLAG_FLOOR = 0.05          # below this, a flag is forgotten

# pattern -> severity of one hit (0..1); tuned to history's hit-rate:
# an auditor resigning or withdrawals halting almost never ends well.
PATTERNS: list[tuple[re.Pattern, float, str]] = [
    (re.compile(r"\b(auditor (?:resigns?|quits|refuses)|unable to sign off|"
                r"adverse audit opinion)\b", re.I), 0.9, "auditor walked"),
    (re.compile(r"\b(halts?|freezes?|suspends?) (?:customer )?withdrawals\b", re.I),
     0.9, "withdrawal halt"),
    (re.compile(r"\b(accounting (?:fraud|irregularit|scandal)|fabricated (?:revenue|sales)|"
                r"cook(?:ed|ing) the books|restat(?:es?|ing|ement))\b", re.I),
     0.8, "accounting fraud/restatement"),
    (re.compile(r"\b(ponzi|pyramid scheme|exit scam)\b", re.I), 0.9, "ponzi allegation"),
    (re.compile(r"\b(short[- ]seller (?:report|attack)|shares? halted|trading halted)\b", re.I),
     0.5, "short-seller report / halt"),
    (re.compile(r"\b(sec (?:probe|subpoena|investigat|charges)|doj (?:probe|charges|investigat)|"
                r"fraud (?:probe|investigation|charges))\b", re.I), 0.6, "regulator probe"),
    (re.compile(r"\b(delays? (?:annual|quarterly|10-k|10-q) (?:report|filing)|"
                r"misses? filing deadline)\b", re.I), 0.5, "delayed filing"),
    (re.compile(r"\b(proof[- ]of[- ]reserves? (?:doubt|question|fail)|commingl\w+|"
                r"rehypothecat\w+|misused customer funds?)\b", re.I), 0.7, "reserves/commingling doubt"),
    (re.compile(r"\b(guaranteed (?:returns?|profits?|yield)|risk[- ]free (?:returns?|yield))\b",
     re.I), 0.6, "'guaranteed returns' marketing"),
    (re.compile(r"\b(whistleblower|internal probe|cfo (?:resigns?|departs?) abruptly)\b", re.I),
     0.4, "whistleblower / abrupt CFO exit"),
]


def _path(settings) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(settings.state_path)),
                        "integrity_flags.json")


def load_flags(settings) -> dict:
    try:
        with open(_path(settings)) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def _decayed(flag: dict, now: float) -> float:
    age_days = max(0.0, (now - flag.get("ts", now)) / 86400.0)
    return flag.get("severity", 0.0) * 0.5 ** (age_days / HALF_LIFE_DAYS)


def current_flags(settings) -> dict[str, dict]:
    """asset node id -> {severity (decayed), reasons}. Forgotten below floor."""
    now = time.time()
    out = {}
    for nid, f in load_flags(settings).items():
        sev = _decayed(f, now)
        if sev >= FLAG_FLOOR:
            out[nid] = {"severity": round(sev, 3), "reasons": f.get("reasons", [])[-4:]}
    return out


def scan_headlines(headlines: list[dict], graph, settings) -> dict[str, dict]:
    """Match integrity patterns to specific assets; update persisted flags.
    Only ASSET nodes are flagged (a sector can't have its auditor resign).
    Returns the hits made this scan."""
    now = time.time()
    flags = load_flags(settings)
    hits: dict[str, dict] = {}
    for h in headlines:
        text = f"{h.get('title', '')} {h.get('summary', '')}"
        matched = [(sev, why) for rx, sev, why in PATTERNS if rx.search(text)]
        if not matched:
            continue
        assets = [nid for nid in graph.match_text(text)
                  if graph.nodes[nid].type == "asset"]
        if not assets:
            continue
        sev = max(s for s, _ in matched)
        why = "; ".join(w for _, w in matched)
        for nid in assets[:3]:
            prev = _decayed(flags.get(nid, {}), now)
            flags[nid] = {
                "severity": round(min(1.0, prev + sev * (1 - prev)), 3),  # saturating accumulate
                "ts": now,
                "reasons": (flags.get(nid, {}).get("reasons", [])
                            + [f"{why}: {h.get('title', '')[:90]}"])[-6:],
            }
            hits[nid] = flags[nid]
    if hits:
        _save(flags, settings)
    return hits


def _save(flags: dict, settings) -> None:
    try:
        os.makedirs(os.path.dirname(_path(settings)), exist_ok=True)
        with open(_path(settings), "w") as fh:
            json.dump(flags, fh, indent=1)
    except OSError:
        pass


def absorb_llm_integrity(events: list[dict], graph, settings) -> dict[str, dict]:
    """The ADAPTIVE tier: the digester flags any story where reported
    numbers/assets/returns may not be real — by mechanisms that need no
    pre-written pattern. The LLM names the entity and judges severity; code
    resolves the entity and merges into the same decaying flag store, so a
    novel fraud is treated identically to a textbook one. Noise events are
    ignored; severity is discounted by event credibility (an anonymous hit
    piece must not nuke a stock)."""
    from ai_investing.brain.deals import resolve
    now = time.time()
    flags = load_flags(settings)
    hits: dict[str, dict] = {}
    for ev in events:
        if ev.get("is_noise"):
            continue
        cred = float(ev.get("credibility", 0.5) or 0.5)
        for item in (ev.get("integrity") or [])[:4]:
            if not isinstance(item, dict):
                continue
            nid = resolve(graph, str(item.get("company", "")))
            if nid is None or graph.nodes[nid].type != "asset":
                continue
            try:
                sev = max(0.0, min(1.0, float(item.get("severity", 0.0)))) * (0.5 + 0.5 * cred)
            except (TypeError, ValueError):
                continue
            if sev < FLAG_FLOOR:
                continue
            mech = str(item.get("mechanism", ""))[:120] or "llm-flagged integrity doubt"
            prev = _decayed(flags.get(nid, {}), now)
            flags[nid] = {
                "severity": round(min(1.0, prev + sev * (1 - prev)), 3),
                "ts": now,
                "reasons": (flags.get(nid, {}).get("reasons", [])
                            + [f"[llm] {mech}"])[-6:],
            }
            hits[nid] = flags[nid]
    if hits:
        _save(flags, settings)
    return hits
