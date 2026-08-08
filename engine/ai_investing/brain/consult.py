"""Inference consultation — the one thing the bot asks you.

WHY THIS REPLACED PER-TRADE APPROVAL.

The old gate (execution/approvals.py) asked "buy NVDA for $4,200 — yes or no?"
once per entry, per book. That question is the wrong one twice over. It arrives
at the end of the chain, where the only honest answer is "I trust the sizing
formula or I don't"; and it arrives many times a day, which trains you to swipe.
The thing you can actually judge better than the machine is the LEAP: the step
from "OPEC cut output" to "this is a real supply squeeze, not a gesture". Get
that wrong and every position downstream of it is wrong, however well sized.

So the bot now asks about the READ, not the order:

    2-3 headlines it saw  ->  the inference it drew  ->  the assumption it rests on
                          ->  👍 agree / 😐 not sure / 👎 disagree

WHAT A TAP ACTUALLY DOES (this is the whole design — a tap that is merely logged
is a comfort blanket, and the user said so).

  1. IT ALWAYS MOVES MONEY, THE NEXT CYCLE. The verdict becomes a multiplier on
     the impulse that reading sends into the graph. Everything downstream —
     node activations, asset impacts, conviction, position size — shrinks or
     grows with it. 👎 does not mean "noted"; it means a $4,200 position comes
     out at ~$1,900, or does not clear the bar at all.

  2. IT IS A WEIGHT, NOT A VETO — because a veto would hand the sizing decision
     back to a human gut, which is the thing this system exists to beat.

  3. AN OVERRIDE COSTS THE BOT SOMETHING AND IS NEVER SILENT. A disagreed
     reading can only reassert itself if fresh evidence clears a RAISED bar
     (OVERRIDE_MULT x the disputed conviction, floor OVERRIDE_FLOOR) — and when
     it does, you are told, with the new headline. An override you cannot see is
     indistinguishable from being ignored.

  4. THE SECOND 👎 IS ABSOLUTE. Say it twice and the reading is blocked outright
     for the TTL, no override path. You never lose the ability to actually stop
     something; you just have to mean it. This filters reflexes from convictions.

Everything — every ask, every tap, every override — appends to
`data/inference_log.jsonl`, which is append-only and never rewritten. That file
is what a later calibration pass will grade to learn how much YOUR taps are
worth (see `trust_factor` below); it is deliberately not graded yet, because
grading it against the bot's own field state would be circular.

NOT GATED, EVER: protective exits, stops, circuit-breaker flattens, blocklist
exits. Safety has never waited for a human here and still doesn't.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

# -- the dial ----------------------------------------------------------------
# Deliberately asymmetric. 😐 is 0.85, not 1.0: "not sure" is a real signal —
# you read the same news and did not find the leap obvious — and treating it as
# silence would throw that away. Silence itself stays 1.0, because an unread
# phone is not a market opinion.
WEIGHTS = {"agree": 1.30, "neutral": 0.85, "disagree": 0.45}
BLOCKED = 0.0                # two 👎 on the same reading
NEUTRAL_WEIGHT = 1.0         # no answer / expired

# What it takes for a disagreed reading to reassert itself. Both must hold: the
# new conviction must be half again what you disputed AND absolutely strong.
# Without the floor, disagreeing with a weak read would make it trivially
# overridable; without the multiple, a strong read could never be disputed at all.
OVERRIDE_MULT = 1.5
OVERRIDE_FLOOR = 0.60

DEFAULT_TTL_H = 72.0         # a market read goes stale in about three days
# MEASURED, NOT GUESSED (2026-08-08). The first value here was 0.35, reasoned
# from "impulse is roughly a conviction in [-1,1]". It is not: impulse is
# polarity x magnitude x credibility x confidence, a product of four sub-1 terms,
# so it piles up near zero. Against 2,564 real events in brain.db the whole
# 30-day distribution was p50 0.022, p99 0.277, max 0.562 — EIGHT events cleared
# 0.35 in a month, and none at all in the last four days. The channel would have
# shipped mute, which is the one failure mode indistinguishable from working.
#
# Replayed over the real stream with covered()/TTL dedup applied, asks per active
# day come out: 0.10 -> 5.4   0.15 -> 3.9   0.20 -> 2.6   0.25 -> 1.9
# 0.20 sits where the user asked to be: a couple a day, none on quiet days, more
# when the news is genuinely busy. The confidence gate below trims it further.
ASK_BAR = 0.20               # |impulse| below this never moves enough to be worth a ping
ASK_MIN_CONFIDENCE = 0.50    # do not ask you to ratify a guess the bot isn't sure of
MAX_ASKS_PER_CYCLE = 2       # a hard cap: flooding you IS the failure mode being fixed


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _paths(settings) -> tuple[str, str]:
    data_dir = os.path.dirname(os.path.abspath(settings.brain.state_path))
    return (os.path.join(data_dir, "inferences.json"),
            os.path.join(data_dir, "inference_log.jsonl"))


class ConsultBook:
    """Live inferences awaiting, or carrying, your verdict.

    Shared state between the engine loop and the chat bot process, whole-file
    read-modify-write — the same contract ProposalBook uses, and fine for the
    same reason: a handful of records, two slow writers.
    """

    def __init__(self, settings, ttl_hours: float = DEFAULT_TTL_H):
        self.path, self.log_path = _paths(settings)
        self.ttl_hours = float(getattr(settings.brain, "consult_ttl_hours", ttl_hours))

    # -- storage -------------------------------------------------------------
    def _load(self) -> list[dict]:
        try:
            with open(self.path) as fh:
                return json.load(fh).get("inferences", [])
        except (OSError, json.JSONDecodeError):
            return []

    def _save(self, rows: list[dict]) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump({"inferences": rows}, fh, indent=1)
        os.replace(tmp, self.path)          # never leave a half-written book

    def _append_log(self, kind: str, rec: dict, **extra) -> None:
        """Append-only history. Every ask, tap and override survives forever —
        this is the evidence a later calibration grades, so it is written even
        when the live book prunes the record away."""
        try:
            with open(self.log_path, "a") as fh:
                fh.write(json.dumps({"kind": kind, "ts": _now().isoformat(),
                                     "id": rec.get("id"), "claim": rec.get("claim"),
                                     "nodes": rec.get("nodes"),
                                     "impulse": rec.get("impulse"),
                                     "verdict": rec.get("verdict"),
                                     "disagrees": rec.get("disagrees", 0),
                                     **extra}) + "\n")
        except OSError:
            pass

    @staticmethod
    def _iid(nodes: list[str], sign: int, ts: str) -> str:
        return hashlib.sha1(f"{'|'.join(sorted(nodes))}|{sign}|{ts}".encode()).hexdigest()[:8]

    def _fresh(self, r: dict) -> bool:
        try:
            return datetime.fromisoformat(r["expires"]) > _now()
        except (KeyError, ValueError):
            return False

    # -- api -----------------------------------------------------------------
    def prune(self) -> None:
        rows = self._load()
        keep = [r for r in rows if self._fresh(r)]
        if len(keep) != len(rows):
            for r in rows:
                if r not in keep:
                    self._append_log("expired", r)
            self._save(keep)

    def live(self) -> list[dict]:
        return [r for r in self._load() if self._fresh(r)]

    def open_asks(self) -> list[dict]:
        """Asked, still fresh, not yet answered."""
        return [r for r in self.live() if not r.get("verdict")]

    def covered(self, nodes: list[str], sign: int) -> dict | None:
        """A live inference already asking about this node+direction, if any.

        Node-and-sign, not text: the same reading arriving three days running in
        three different wordings is ONE question, and asking it three times is
        the flooding this module exists to prevent.
        """
        for r in self.live():
            if r.get("sign") == sign and set(r.get("nodes") or []) & set(nodes):
                return r
        return None

    def file(self, claim: str, assumption: str, nodes: list[str], impulse: float,
             confidence: float, headlines: list[dict], direction: str = "") -> dict:
        sign = 1 if impulse >= 0 else -1
        ts = _now().isoformat()
        rec = {
            "id": self._iid(nodes, sign, ts),
            "claim": claim[:400], "assumption": assumption[:400],
            "direction": direction[:120],
            "nodes": nodes[:3], "sign": sign,
            "impulse": round(float(impulse), 4),
            "conviction": round(abs(float(impulse)), 4),
            "confidence": round(float(confidence), 3),
            "headlines": [{"title": (h.get("title") or h.get("headline") or "")[:180],
                           "source": (h.get("source") or "")[:40]} for h in headlines[:3]],
            "ts": ts,
            "expires": (_now() + timedelta(hours=self.ttl_hours)).isoformat(),
            "verdict": None, "disagrees": 0, "overrides": 0, "decided": None,
        }
        rows = self._load()
        rows.append(rec)
        self._save(rows)
        self._append_log("asked", rec)
        return rec

    def decide(self, iid: str, verdict: str) -> dict | None:
        """Record your tap. A repeat 👎 on the same reading escalates to a block.

        Returns the updated record, or None if it expired or is unknown.
        """
        rows = self._load()
        for r in rows:
            if r["id"] != iid or not self._fresh(r):
                continue
            if verdict == "disagree":
                r["disagrees"] = int(r.get("disagrees", 0)) + 1
            r["verdict"] = verdict
            r["decided"] = _now().isoformat()
            self._save(rows)
            self._append_log("decided", r, verdict=verdict)
            return r
        return None

    def note_override(self, iid: str, headline: str, conviction: float) -> dict | None:
        """The bot outvoted you on this reading. Counted, logged, and reported —
        an override the user cannot see is just the bot ignoring them."""
        rows = self._load()
        for r in rows:
            if r["id"] == iid and self._fresh(r):
                r["overrides"] = int(r.get("overrides", 0)) + 1
                r["last_override"] = _now().isoformat()
                self._save(rows)
                self._append_log("override", r, headline=headline[:180],
                                 new_conviction=round(conviction, 4))
                return r
        return None

    def record(self) -> dict:
        """Your running tally, for /inferences. Read from the append-only log so
        it survives pruning."""
        counts = {"asked": 0, "agree": 0, "neutral": 0, "disagree": 0,
                  "blocked": 0, "overrides": 0}
        try:
            with open(self.log_path) as fh:
                for line in fh:
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if row.get("kind") == "asked":
                        counts["asked"] += 1
                    elif row.get("kind") == "decided":
                        v = row.get("verdict")
                        if v in counts:
                            counts[v] += 1
                        if v == "disagree" and int(row.get("disagrees", 0)) >= 2:
                            counts["blocked"] += 1
                    elif row.get("kind") == "override":
                        counts["overrides"] += 1
        except OSError:
            pass
        return counts


# -- how much your taps are worth --------------------------------------------
def trust_factor(settings) -> float:
    """Scales how far a 👎 pulls, in [0.5, 2.0]; 1.0 until calibrated.

    THIS IS THE HOOK, NOT THE CALIBRATION. The intended end state is that the
    log is graded against realized prices — if your disagreements keep being
    right, a 👎 damps harder; if they keep being wrong, it damps less and you
    are told. That grading is NOT implemented, and is deliberately not faked:
    the only outcome data reachable from here today is the brain's own field,
    and grading your objection against a field your objection already damped is
    circular — it would manufacture agreement with itself and read as learning.

    Until a price-based grader exists, this reads an operator-set override from
    data/inference_trust.json and otherwise returns 1.0. Damping code calls it,
    so calibration lands here without touching anything else.
    """
    try:
        data_dir = os.path.dirname(os.path.abspath(settings.brain.state_path))
        with open(os.path.join(data_dir, "inference_trust.json")) as fh:
            return max(0.5, min(2.0, float(json.load(fh).get("factor", 1.0))))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return 1.0


def weight_for(rec: dict, trust: float = 1.0) -> float:
    """The multiplier a decided inference imposes on its own impulse."""
    if int(rec.get("disagrees", 0)) >= 2:
        return BLOCKED                       # second 👎: absolute, no trust scaling
    verdict = rec.get("verdict")
    if verdict not in WEIGHTS:
        return NEUTRAL_WEIGHT
    w = WEIGHTS[verdict]
    if w >= 1.0:
        return round(1.0 + (w - 1.0) * trust, 4)   # trust deepens agreement too
    # rounded: an untrusted-yet trust of 1.0 must return the dial's stated value
    # exactly, or the number quoted back to the user in chat drifts by float dust
    return round(max(0.05, 1.0 - (1.0 - w) * trust), 4)


# -- the two calls the brain makes -------------------------------------------
def damp(events: list[dict], settings) -> list[dict]:
    """Scale each event's impulse by your live verdict on the matching reading.

    Called from Brain.think() the moment impulses are known and BEFORE they
    propagate, so a verdict lands on the field the very next cycle — that
    immediacy is what makes the tap a decision rather than a survey.

    Mutates events in place (adds `consult_weight` / `consult_id` for the trace)
    and RETURNS the override notices the caller must send. Overrides are the
    only thing this function makes noise about; a routine damping is visible in
    the field, not in your phone.
    """
    book = ConsultBook(settings)
    book.prune()
    decided = [r for r in book.live() if r.get("verdict")]
    if not decided:
        return []
    trust = trust_factor(settings)
    notices: list[dict] = []

    for ev in events:
        if ev.get("is_noise"):
            continue
        imp = float(ev.get("impulse", 0.0) or 0.0)
        if imp == 0.0:
            continue
        nodes, sign = set(ev.get("nodes") or []), (1 if imp >= 0 else -1)
        for rec in decided:
            # SAME NODE, SAME DIRECTION = the same reading recurring. An opposite-
            # signed event on that node is NEW information, not the disputed read,
            # and damping it would silence the very evidence that should change
            # your mind.
            if rec.get("sign") != sign or not (nodes & set(rec.get("nodes") or [])):
                continue
            w = weight_for(rec, trust)
            if w >= 1.0:
                ev["impulse"] = round(imp * w, 4)
                ev["consult_weight"], ev["consult_id"] = w, rec["id"]
                break

            # THE OVERRIDE. Only a 👎 can be outvoted — 😐 is a shrug you gave on
            # purpose and always damps. A block never can be.
            if (rec.get("verdict") == "disagree"
                    and int(rec.get("disagrees", 0)) < 2
                    and abs(imp) >= max(OVERRIDE_FLOOR,
                                        float(rec.get("conviction", 0.0)) * OVERRIDE_MULT)):
                book.note_override(rec["id"], ev.get("headline") or ev.get("summary", ""),
                                   abs(imp))
                ev["consult_override"] = rec["id"]
                notices.append({"rec": rec, "event": ev, "conviction": abs(imp)})
                break

            ev["impulse"] = round(imp * w, 4)
            ev["consult_weight"], ev["consult_id"] = w, rec["id"]
            break
    return notices


def harvest(events: list[dict], settings, headlines: list[dict] | None = None) -> list[dict]:
    """Pick the readings worth asking you about, and file them.

    Event-driven by design (your choice over a daily digest): the bot asks when
    it forms a genuinely new interpretation strong enough to move money, which
    means some days it says nothing at all. Silence here is meaningful — it
    means nothing crossed the bar, not that the bot forgot.

    Three filters, all necessary:
      * |impulse| >= ASK_BAR — below this the reading cannot move a position
        enough for your opinion of it to matter.
      * confidence >= ASK_MIN_CONFIDENCE — never ask you to ratify a guess.
      * not already covered — one live question per node+direction (see covered()).
    """
    book = ConsultBook(settings)
    book.prune()
    bar = float(getattr(settings.brain, "consult_ask_bar", ASK_BAR))
    cap = int(getattr(settings.brain, "consult_max_asks", MAX_ASKS_PER_CYCLE))

    candidates = [
        ev for ev in events
        if not ev.get("is_noise")
        and (ev.get("nodes") or [])
        and abs(float(ev.get("impulse", 0.0) or 0.0)) >= bar
        and float(ev.get("confidence", 0.0) or 0.0) >= ASK_MIN_CONFIDENCE
    ]
    candidates.sort(key=lambda e: -abs(float(e.get("impulse", 0.0) or 0.0)))

    filed: list[dict] = []
    for ev in candidates:
        if len(filed) >= cap:
            break
        nodes = list(ev.get("nodes") or [])[:3]
        sign = 1 if float(ev["impulse"]) >= 0 else -1
        if book.covered(nodes, sign):
            continue
        heads = [{"title": ev.get("headline") or ev.get("summary", ""),
                  "source": ev.get("source", "")}]
        heads += _corroborating(ev, headlines or [], limit=2)
        filed.append(book.file(
            claim=_claim(ev), assumption=_assumption(ev), nodes=nodes,
            impulse=float(ev["impulse"]), confidence=float(ev.get("confidence", 0.5)),
            headlines=heads, direction=ev.get("direction", "")))
    return filed


def _corroborating(ev: dict, headlines: list[dict], limit: int = 2) -> list[dict]:
    """Other headlines from the same batch that share vocabulary with this one —
    the 2-3 lines of source material you asked to see alongside the read, so the
    leap can be judged rather than taken on faith."""
    own = (ev.get("headline") or ev.get("summary", "")).lower()
    words = {w for w in own.replace(",", " ").split() if len(w) > 4}
    if not words:
        return []
    scored = []
    for h in headlines:
        title = (h.get("title") or "").strip()
        if not title or title.lower() == own:
            continue
        overlap = len({w for w in title.lower().split() if len(w) > 4} & words)
        if overlap >= 2:
            scored.append((overlap, {"title": title, "source": h.get("source", "")}))
    scored.sort(key=lambda t: -t[0])
    return [h for _, h in scored[:limit]]


def _claim(ev: dict) -> str:
    """The interpretation, in the bot's own words — what it decided the news MEANS.

    `direction` is the digester's reading ("less oil supply"); `summary` is what
    happened. The claim is the leap between them, which is the thing under review.
    """
    direction = (ev.get("direction") or "").strip()
    summary = (ev.get("summary") or ev.get("headline") or "").strip()
    if direction and summary:
        # QUOTES, NOT ASTERISKS. The claim gets embedded inside an _italic_ line
        # by /inferences, and Telegram's legacy Markdown does not nest — a bold
        # span inside italics 400s and drops the message to the plain-text
        # fallback. Quotes carry the same emphasis and always render.
        return f"{summary} — I read this as “{direction}”."
    return direction or summary or "(no reading)"


def _assumption(ev: dict) -> str:
    """What the reading rests on. The digester supplies this when it can (see the
    `assumption` field in brain/events.py); otherwise it is composed from what the
    reading already commits to, which is honest but blunter."""
    stated = (ev.get("assumption") or "").strip()
    if stated:
        return stated
    bits = []
    if ev.get("credibility") is not None:
        bits.append(f"the reporting is accurate (credibility {float(ev['credibility']):.2f})")
    if ev.get("direction"):
        bits.append(f"the effect is genuinely “{ev['direction']}” and not already priced in")
    if ev.get("magnitude") is not None:
        bits.append(f"it matters at about {float(ev.get('magnitude', 0)):.0%} of a major move")
    return "; ".join(bits) or "that the current picture holds"


# -- the message -------------------------------------------------------------
def ask_text(rec: dict) -> str:
    heads = "\n".join(f"• {h['title']}" + (f" _({h['source']})_" if h.get("source") else "")
                      for h in rec.get("headlines", []))
    return (
        "🧠 *Do you agree with this read?*\n\n"
        f"📰 *What I saw:*\n{heads or '• (no headline captured)'}\n\n"
        f"🔍 *My read:* {rec['claim']}\n"
        f"🤔 *Resting on:* {rec['assumption']}\n\n"
        "_Your tap weights this reading across every book — it is not a trade "
        "approval, and selling to protect you never waits for you. "
        "👎 twice on the same read blocks it outright._")


def ask_buttons(rec: dict) -> list[list[tuple[str, str]]]:
    return [[("👍 agree", f"ia:{rec['id']}"),
             ("😐 not sure", f"im:{rec['id']}"),
             ("👎 disagree", f"ix:{rec['id']}")]]


def override_text(notice: dict) -> str:
    rec, ev = notice["rec"], notice["event"]
    return (
        "⚖️ *Going against your 👎* — new evidence cleared a higher bar.\n\n"
        f"You disagreed with: _{rec['claim']}_\n"
        f"(conviction then {float(rec.get('conviction', 0)):.2f})\n\n"
        f"📰 Since then: {(ev.get('headline') or ev.get('summary', ''))[:200]}\n"
        f"Conviction now *{notice['conviction']:.2f}* — past the "
        f"{max(OVERRIDE_FLOOR, float(rec.get('conviction', 0)) * OVERRIDE_MULT):.2f} "
        "it needed to outvote you.\n\n"
        "_Tap 👎 again to block this read outright — a second disagree cannot be "
        "overridden._")


def override_buttons(notice: dict) -> list[list[tuple[str, str]]]:
    return [[("👎 block it", f"ix:{notice['rec']['id']}"),
             ("👍 fair enough", f"ia:{notice['rec']['id']}")]]
