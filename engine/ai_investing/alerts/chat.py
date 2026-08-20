"""Two-way Telegram chat: discuss the brain, the book, and the trades from your phone.

Run alongside the engine:   python3 -m ai_investing.main --chat

Long-polls getUpdates (stdlib urllib, no SDK) and answers ONLY the configured
TELEGRAM_CHAT_ID — anyone else messaging the bot is ignored. Commands are handled
locally from the engine's state files (free, instant); free-form questions go to
the LLM (local Qwen first) with a compact snapshot of the brain, the advice list,
and the portfolio as context, so the answers are about YOUR system, not generic
market chat.

The chat can *read* everything but can *write* only through the sanctioned
user-input overlay (views/stance/blocklist) — the same one the dashboard uses.
It cannot place orders, change risk limits, or touch safety settings.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone

HELP = """*AI-Investing chat* — talk to your engine.

/advise — the current top-10 trade list, with reasons
/inferences — my reads of the news awaiting your 👍😐👎, what
   you've already weighted, and your running record
/pending — legacy per-trade approvals (only if TRADE_APPROVAL=true)
/brain — regime, emotions, mood, what's ringing in the field
/portfolio — equity, positions, you-vs-formula
/assets — one-glance totals: cash + holdings per book, nothing else
/news — what was digested recently (signal vs noise)
/submit <text> — feed in a real article, trend, or your own take.
   Digested for real on the next engine cycle (not a what-if) and
   trusted like a serious outlet by default, since you chose to type it.
/simulate <headline> — ripple a hypothetical through the graph, no
   memory, right now — for testing a "what if", not for real news
/view SYM=0.5 — set your tilt on an asset (-1..1)
/block SYM · /unblock SYM — never / again trade a symbol
/stance aggressive|normal|cautious|defensive|cash
/help — this menu

The one thing I ask you unprompted is whether you agree with a READ
of the news — headlines, my inference, the assumption it rests on.
👍 sizes it up, 😐 and 👎 damp it, 👎 twice blocks it outright. I can
only outvote a 👎 on much stronger evidence, and I'll say when I do.

Most replies come with tap buttons, so you rarely need to type
commands. Anything else: just ask in plain words — I'll answer from
the brain's current state (local model, free)."""

_SYSTEM = """You are the user's own trading engine ("the brain") chatting on Telegram.
Answer in plain, friendly language, 2-6 short sentences, no headers. Ground every
answer in the CONTEXT below — it is your actual current state. If asked something
the context can't answer, say so honestly. Never invent prices or news. You give
decision support from your own analysis, and always note the user decides; you
cannot place orders from chat.

CONTEXT:
{context}

USER: {question}"""


class ChatBot:
    def __init__(self, settings):
        self.settings = settings
        self.token = settings.alerts.telegram_bot_token
        self.chat_id = str(settings.alerts.telegram_chat_id)
        self.data_dir = os.path.dirname(os.path.abspath(settings.state_path))
        self.offset_path = os.path.join(self.data_dir, "chat_state.json")
        self.offset, self.history = self._load_state()   # history survives restarts

    # -- telegram plumbing ----------------------------------------------------
    def _api(self, method: str, params: dict, timeout: int = 60) -> dict:
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        data = urllib.parse.urlencode(params).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())

    def _send(self, text: str, buttons: list[list[tuple[str, str]]] | None = None) -> None:
        """buttons: rows of (label, callback_data) rendered as tappable inline keys."""
        chunks = [text[i:i + 3900] for i in range(0, max(1, len(text)), 3900)]
        for i, chunk in enumerate(chunks):
            params = {"chat_id": self.chat_id, "text": chunk,
                      "parse_mode": "Markdown", "disable_web_page_preview": "true"}
            if buttons and i == len(chunks) - 1:   # keyboard on the last chunk
                params["reply_markup"] = json.dumps({"inline_keyboard": [
                    [{"text": lbl, "callback_data": data[:64]} for lbl, data in row]
                    for row in buttons]})
            try:
                self._api("sendMessage", params, timeout=15)
            except Exception:
                # markdown can 400 on odd characters — retry plain
                try:
                    params["parse_mode"] = ""
                    self._api("sendMessage", params, timeout=15)
                except Exception:
                    pass

    def _load_state(self) -> tuple[int, list[tuple[str, str]]]:
        try:
            with open(self.offset_path) as fh:
                st = json.load(fh)
            return int(st.get("offset", 0)), [tuple(t) for t in st.get("history", [])][-12:]
        except (OSError, ValueError, json.JSONDecodeError):
            return 0, []

    def _save_state(self) -> None:
        try:
            with open(self.offset_path, "w") as fh:
                json.dump({"offset": self.offset,
                           "history": [list(t) for t in self.history[-12:]]}, fh)
        except OSError:
            pass

    # -- state readers ----------------------------------------------------------
    def _read(self, name: str) -> dict:
        paths = {"brain.json": self.settings.brain.state_path,
                 "advice.json": self.settings.brain.advice_path,
                 "state.json": self.settings.state_path}
        try:
            with open(paths.get(name, os.path.join(self.data_dir, name))) as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            return {}

    def _context(self) -> str:
        """Compact snapshot the LLM answers from."""
        brain = self._read("brain.json")
        advice = self._read("advice.json")
        state = self._read("state.json")
        reg = brain.get("regime", {})
        lab = reg.get("labels", {})
        parts = [
            f"Regime: risk {lab.get('risk_appetite')}, rates {lab.get('rate_trajectory')}, "
            f"USD {lab.get('dollar_trend')}, inflation {lab.get('inflation_trend')}, "
            f"china {lab.get('china_stance')}; tension {reg.get('geopolitical_tension')}, "
            f"stability {reg.get('stability')}, fragility {reg.get('fragility')}",
            f"Crowd emotion: {reg.get('emotion_label')} (fear {reg.get('fear')}, greed {reg.get('greed')}); "
            f"my mood: {reg.get('mood_label')} (confidence {reg.get('mood_confidence')}, "
            f"caution {reg.get('mood_caution')})",
            "Strongest field activations: " + ", ".join(
                f"{k} {v:+.2f}" for k, v in list(brain.get("activations", {}).items())[:10]),
            "Delayed effects queued: " + ("; ".join(
                f"{p.get('via')}->{p.get('node')} {p.get('contribution'):+.2f} due {str(p.get('due'))[:10]}"
                for p in brain.get("pending_effects", [])[:5]) or "none"),
            "Recent events: " + ("; ".join(
                f"[{'NOISE' if e.get('is_noise') else 'signal'}] {e.get('summary','')[:90]}"
                for e in brain.get("events", [])[:8]) or "none this cycle"),
            "Top trades: " + ("; ".join(
                f"#{t['rank']} {t['direction']} {t['symbol']} ({t['score']:+.2f}) because {t['chain']}"
                for t in (advice.get("trades") or [])[:10]) or "none clear the bar"),
            f"Portfolio: equity ${state.get('equity', 0):,.0f}, cash ${state.get('cash', 0):,.0f}, "
            f"positions: " + (", ".join(
                f"{p['symbol']} {p['qty']:+.3f} (pnl ${p['pnl']:,.0f})"
                for p in state.get("positions", [])[:12]) or "none"),
            f"You-vs-formula: {json.dumps({k: v for k, v in (state.get('comparison') or {}).items() if k != 'assets'})}",
        ]
        if self.history:
            parts.append("Recent chat: " + " | ".join(f"U:{u[:60]} ME:{b[:60]}"
                                                      for u, b in self.history[-3:]))
        return "\n".join(parts)

    # -- command handlers ---------------------------------------------------------
    MENU = [[("📊 advise", "c:/advise"), ("🧠 brain", "c:/brain")],
            [("💼 portfolio", "c:/portfolio"), ("📰 news", "c:/news")],
            [("💰 assets", "c:/assets"), ("⚖️ my reads", "c:/inferences")]]

    # Registered with Telegram via setMyCommands so "/" pops the native
    # autocomplete list in the client (the same mechanism BotFather uses for
    # its own /newbot etc.) — this repo answers commands by parsing text, which
    # gives the bot no menu unless it explicitly tells Telegram what exists.
    COMMANDS = [
        ("advise", "Top trade ideas, with reasons"),
        ("inferences", "News reads awaiting your 👍/😐/👎"),
        ("pending", "Legacy per-trade approvals"),
        ("brain", "Regime, mood, what's active"),
        ("portfolio", "Equity, positions, you vs formula"),
        ("assets", "Cash + holdings, one line per book"),
        ("news", "What was digested recently"),
        ("submit", "Feed in real news/trend/opinion to digest"),
        ("simulate", "Ripple a hypothetical headline (no memory)"),
        ("view", "Set your tilt on an asset, e.g. NVDA=0.5"),
        ("block", "Never trade a symbol"),
        ("unblock", "Allow a symbol again"),
        ("stance", "aggressive|normal|cautious|defensive|cash"),
        ("help", "Show this command menu"),
    ]

    def handle(self, text: str) -> tuple[str, list | None]:
        """Returns (message, inline_buttons)."""
        text = text.strip()
        low = text.lower()
        if low in ("/start", "/help", "help", "/menu"):
            return HELP, self.MENU
        if low.startswith("/advise"):
            return self._fmt_advice()
        if low.startswith("/pending"):
            return self._fmt_pending()
        if low.startswith(("/inferences", "/reads", "/inference")):
            return self._fmt_inferences()
        if low.startswith("/brain"):
            return self._fmt_brain(), self.MENU
        if low.startswith("/assets") or low.startswith("/cash"):
            return self._fmt_assets(), self.MENU
        if low.startswith("/portfolio") or low.startswith("/pnl"):
            return self._fmt_portfolio(), self.MENU
        if low.startswith("/news"):
            return self._fmt_news(), self.MENU
        if low.startswith("/simulate"):
            headline = text[len("/simulate"):].strip()
            return (self._fmt_simulate(headline) if headline
                    else "Give me a headline: /simulate PBOC cuts rates"), None
        if low.startswith("/submit"):
            body = text[len("/submit"):].strip()
            return (self._submit_news(body) if body
                    else "Paste the article/trend/take after the command, e.g.\n"
                         "/submit Unitree's IPO is heavily oversubscribed per..."), None
        if low.startswith(("/view", "/block", "/unblock", "/stance")):
            return self._apply_view(text), None
        return self._ask_llm(text), self.MENU

    def handle_callback(self, data: str) -> tuple[str, list | None]:
        """Route a tapped inline button. Data forms:
        c:<command>  — run a chat command
        v:SYM:VAL    — set a view tilt on SYM
        b:SYM        — block SYM"""
        kind, _, rest = data.partition(":")
        if kind == "c" and rest.startswith("/"):
            return self.handle(rest)
        if kind == "v":
            sym, _, val = rest.partition(":")
            return self._apply_view(f"/view {sym}={val}"), None
        if kind == "b":
            return self._apply_view(f"/block {rest}"), None
        if kind in ("ap", "rj"):
            return self._decide_proposal(rest, approved=(kind == "ap")), None
        if kind in ("ia", "im", "ix"):
            return self._decide_inference(
                rest, {"ia": "agree", "im": "neutral", "ix": "disagree"}[kind]), None
        return "That button confused me — try /help.", self.MENU

    def _book(self):
        from ai_investing.execution.approvals import ProposalBook
        return ProposalBook(self.settings.proposals_path, self.settings.approval_ttl_hours)

    def _decide_proposal(self, pid: str, approved: bool) -> str:
        p = self._book().decide(pid, approved)
        if p is None:
            return "That proposal already expired or was decided — /pending shows what's live."
        if approved:
            return (f"✅ Approved: *{p['side'].upper()} {p['symbol']}*. "
                    "Executes on the next engine cycle (sized fresh at market). "
                    "_Risk & safety limits still cap it._")
        return f"❌ Skipped {p['symbol']} — I won't re-ask until this idea expires."

    # -- inference consultation (brain/consult.py) ---------------------------
    def _decide_inference(self, iid: str, verdict: str) -> str:
        """Confirm the tap by saying what it just DID. A reply of 'noted' is how
        a steering control starts feeling like a survey."""
        from ai_investing.brain import consult
        book = consult.ConsultBook(self.settings)
        rec = book.decide(iid, verdict)
        if rec is None:
            return ("That read already expired — /inferences shows what's live. "
                    "_An expired read carries no weight either way._")
        w = consult.weight_for(rec, consult.trust_factor(self.settings))
        claim = rec["claim"][:120]
        if w == consult.BLOCKED:
            return (f"🚫 *Blocked* — that's your second 👎 on _{claim}_\n\n"
                    f"It now contributes *nothing* for the next "
                    f"{book.ttl_hours:g}h, and no amount of fresh evidence can "
                    "override it. Positions already resting on it get no new size.")
        if verdict == "agree":
            return (f"👍 Noted and *weighted up ×{w:.2f}* — _{claim}_\n\n"
                    "Everything downstream of this read sizes bigger from the next "
                    "cycle. _Risk and safety limits still cap it._")
        if verdict == "neutral":
            return (f"😐 *Weighted down ×{w:.2f}* — _{claim}_\n\n"
                    "Not a veto: your scepticism shrinks it, the reading still counts. "
                    "_'Not sure' is a real signal here, not a shrug._")
        bar = max(consult.OVERRIDE_FLOOR,
                  float(rec.get("conviction", 0.0)) * consult.OVERRIDE_MULT)
        return (f"👎 *Damped ×{w:.2f}* — _{claim}_\n\n"
                f"Effective from the next cycle: every position resting on this read "
                f"sizes down, and weak ones stop clearing the bar.\n"
                f"I'll only go against you if fresh evidence pushes this past "
                f"*{bar:.2f}* conviction — and I'll tell you when it does. "
                "_Tap 👎 again on that message to block it outright._")

    def _fmt_inferences(self) -> tuple[str, list | None]:
        """/inferences — what's open, what you've damped, and your running record."""
        from ai_investing.brain import consult
        book = consult.ConsultBook(self.settings)
        book.prune()
        trust = consult.trust_factor(self.settings)
        live = book.live()
        lines, buttons = [], []

        openq = [r for r in live if not r.get("verdict")]
        if openq:
            lines.append("🧠 *Waiting on your read:*")
            for r in openq:
                lines.append(f"\n• _{r['claim'][:160]}_\n  🤔 {r['assumption'][:140]}")
                buttons.append([("👍 agree", f"ia:{r['id']}"),
                                ("😐 not sure", f"im:{r['id']}"),
                                ("👎 disagree", f"ix:{r['id']}")])
        else:
            lines.append("🧠 Nothing waiting on your read.")

        decided = [r for r in live if r.get("verdict")]
        if decided:
            lines.append("\n⚖️ *Currently weighted by you:*")
            for r in decided:
                w = consult.weight_for(r, trust)
                tag = "🚫 blocked" if w == consult.BLOCKED else f"×{w:.2f}"
                ov = f" · outvoted {r['overrides']}×" if r.get("overrides") else ""
                lines.append(f"• {tag}{ov} — _{r['claim'][:120]}_")

        c = book.record()
        lines.append(
            f"\n📊 *Your record:* {c['asked']} asked · 👍{c['agree']} 😐{c['neutral']} "
            f"👎{c['disagree']} · {c['blocked']} blocked · outvoted {c['overrides']}×")
        if trust != 1.0:
            lines.append(f"_Your taps currently pull ×{trust:.2f} of standard._")
        return "\n".join(lines), (buttons or self.MENU)

    def _fmt_pending(self) -> tuple[str, list | None]:
        pend = self._book().pending()
        if not pend:
            return "Nothing waiting on you — no pending entry proposals.", self.MENU
        lines = ["⏳ *Waiting for your call* (pretend money):"]
        buttons = []
        for p in pend:
            verb = "Buy" if p["side"] == "buy" else "Bet against"
            tag = "🏛 investing" if p.get("horizon") == "long" else "⚡ trading"
            lines.append(
                f"\n{tag} · *{verb} {p.get('label', p['symbol'])}* ({p['symbol']}) — "
                f"about ${p.get('notional', abs(p['qty']) * p['price']):,.0f}\n"
                f"💡 {p.get('why', p['reason'] or 'engine conviction')}\n"
                f"🗺 {p.get('plan', 'hold while the reasons hold; automatic safety stop')}\n"
                f"_expires {p['expires'][:16]}Z_")
            buttons.append([(f"✅ yes, {verb.lower()} {p['symbol']}", f"ap:{p['id']}"),
                            ("❌ skip", f"rj:{p['id']}")])
        return "\n".join(lines), buttons

    def _fmt_advice(self) -> tuple[str, list | None]:
        a = self._read("advice.json")
        trades = a.get("trades") or []
        if not trades:
            return ("Nothing clears the bar right now — the field is quiet. "
                    "That IS the advice."), self.MENU
        lines = [f"🧠 *Top trades* (mood {a.get('mood')}, conviction ×{a.get('conviction_multiplier')})"]
        buttons: list[list[tuple[str, str]]] = []
        for t in trades:
            d = "🟩 LONG" if t["direction"] == "long" else "🟥 AVOID (expect to lag)"
            lines.append(f"*#{t['rank']}* {d} *{t['symbol']}* ({t['score']:+.2f}, wt≤{t['weight_suggestion']:.0%})\n"
                         f"   _{t['chain']}_\n"
                         f"   ⛔ invalidated by: _{t.get('invalidation', '?')}_")
        for t in trades[:4]:   # tap-to-act on the strongest calls
            sym = t["symbol"]
            tilt = "0.4" if t["direction"] == "long" else "-0.4"
            arrow = "👍 agree" if t["direction"] == "long" else "👎 agree (avoid)"
            buttons.append([(f"{arrow} {sym}", f"v:{sym}:{tilt}"),
                            (f"🚫 never trade {sym}", f"b:{sym}")])
        lines.append("_Tap to feed a view into sizing, or reply /view SYM=0.5. "
                     "Views tilt the formula; risk & safety still cap everything._")
        return "\n".join(lines), buttons

    def _fmt_brain(self) -> str:
        b = self._read("brain.json")
        reg = b.get("regime", {})
        lab = reg.get("labels", {})
        act = ", ".join(f"{k} {v:+.2f}" for k, v in list(b.get("activations", {}).items())[:6])
        fired = "; ".join(s.get("implication", "") for s in b.get("scenarios_fired", [])) or "none"
        return (f"🌍 *World*: risk {lab.get('risk_appetite')}, rates {lab.get('rate_trajectory')}, "
                f"USD {lab.get('dollar_trend')}, china {lab.get('china_stance')}\n"
                f"😨 crowd: {reg.get('emotion_label')} (fear {reg.get('fear')}, greed {reg.get('greed')})\n"
                f"🧠 my mood: *{reg.get('mood_label')}* — confidence {reg.get('mood_confidence')}, "
                f"caution {reg.get('mood_caution')}\n"
                f"📡 ringing now: {act or 'quiet'}\n"
                f"🎯 scenarios fired: {fired}")

    def _read_friend_fund(self) -> dict:
        """Latest snapshot from scripts/external_fund_pull.py (a fund a friend
        trades manually, not this engine). List on disk, newest entry last."""
        path = os.path.join(self.data_dir, "external_assets", "friend_fund.json")
        try:
            with open(path) as fh:
                history = json.load(fh)
            return history[-1] if history else {}
        except (OSError, IndexError, json.JSONDecodeError):
            return {}

    def _fmt_assets(self) -> str:
        """/assets — the whole balance sheet in six lines. /portfolio already
        exists but lists every position; this is the deliberately-boring
        version for a daily glance: per book, one line of equity / cash /
        position count, then one total. No positions, no pnl breakdown."""
        import os as _os
        seeds = {
            "📈 trading": float(self.settings.starting_cash),
            "🏛 investing": float(getattr(self.settings, "invest_starting_cash", 0) or 0),
            "⚡ event sleeve": float(_os.environ.get("EVENT_START_CASH", 0) or 0),
            "₿ crypto": float(_os.environ.get("CRYPTO_START_CASH", 0) or 0),
            "⚡₿ crypto event": float(_os.environ.get("CRYPTO_EVENT_START_CASH", 0) or 0),
        }
        books = []
        unpriced = []          # books whose equity could not be read at all
        s = self._read("state.json")
        if s:
            books.append(("📈 trading", float(s.get("equity", 0) or 0),
                          float(s.get("cash", 0) or 0), s.get("positions") or []))
        for icon_title, fname in (("🏛 investing", "invest_state.json"),
                                  ("⚡ event sleeve", "event_state.json"),
                                  ("₿ crypto", "crypto_state.json"),
                                  ("⚡₿ crypto event", "crypto_event_state.json")):
            blob = self._read(fname)
            book = blob.get("broker") if isinstance(blob.get("broker"), dict) else blob
            if not book:
                continue
            cash = float(book.get("cash", 0) or 0)
            eq = blob.get("equity", book.get("equity"))
            positions = book.get("positions") or []
            if eq is None:
                # NEVER fall back to cash. `equity == cash` while positions are
                # open is the exact phantom-valuation signature of §4.7, where an
                # outage priced a short book at zero and the breaker flattened it
                # against a number that never happened. CircuitBreaker.check
                # already refuses to act on an unreadable equity; a display that
                # quietly renders cash instead would state that fiction as fact,
                # on the one line a person actually glances at (§4.15/10).
                unpriced.append((icon_title, cash, len(positions)))
                continue
            books.append((icon_title, float(eq), cash, positions))
        if not books and not unpriced:
            return "No book state on disk yet — engine warming up?"
        lines = ["💰 *Assets on hand*"]
        seed_total = 0.0
        for title, eq, cash, positions in books:
            seed = seeds.get(title, 0.0)
            seed_total += seed
            # "+0"/"-0" for a book that has barely moved reads as a rendering
            # fault rather than as a number. Say what it means instead.
            pnl = ""
            if seed:
                d = eq - seed
                pnl = "  flat" if abs(d) < 1 else f"  {d:+,.0f}"
            # TWO different questions, and conflating them has now caused a
            # mistake in each direction:
            #   NET (long - short) is what the equity is MADE OF. cash + net
            #     always reconciles to equity, so it belongs beside cash.
            #   GROSS (long + short) is what is AT RISK. A short's proceeds sit
            #     in cash while the shares are still owed, so netting hid it:
            #     the investing book read "invested $2,094" against $9,718 of
            #     real exposure — 96% of the book, shown as 21%.
            # Reporting only gross was no better: it does not reconcile with
            # anything, yet sat where the reconciling number used to be, so on a
            # long-only book cash + gross happened to equal equity and taught the
            # reader to add — then broke on the one book with shorts. Show both,
            # name both, and never place them where they invite addition.
            longs = sum(float(p.get("qty", 0) or 0) * float(p.get("price", 0) or 0)
                        for p in positions if float(p.get("qty", 0) or 0) > 0)
            shorts = sum(-float(p.get("qty", 0) or 0) * float(p.get("price", 0) or 0)
                         for p in positions if float(p.get("qty", 0) or 0) < 0)
            # NET is derived as eq - cash, not recomputed from qty * price, so
            # "cash + net reconciles to equity" holds BY CONSTRUCTION. It used
            # to recompute via qty * price, which silently assumes cash already
            # reflects the full entry proceeds/outlay of every open position —
            # true for a paper book, false for a margined futures position
            # (opening one locks margin OUT of cash instead), which read a
            # flat book as thousands of dollars invested in the wrong direction.
            held = f"cash ${cash:,.0f} + ${eq - cash:,.0f} invested"
            # Gated on gross DIFFERING from net, not on `shorts > 0`. Deriving
            # net as `eq - cash` (above) made the shorts-only gate wrong for a
            # third kind of book: on a margined futures book `cash` is wallet
            # balance (margin locked in a position is still inside it) so net
            # collapses to just unrealized P&L. A LONG-only futures book — the
            # ₿ crypto book, live and long_only — then rendered $4.6k of open
            # position as "cash $4,998 + $17 invested", i.e. as flat, with no
            # at-risk clause because it had no shorts. This is the same test
            # the footer below already applies to the portfolio total.
            if longs + shorts - (eq - cash) > 1:
                held += (f" · *${longs + shorts:,.0f} at risk* "
                         f"(${longs:,.0f} long, ${shorts:,.0f} short)")
            lines.append(f"{title}: *${eq:,.0f}*{pnl}  ({held} in {len(positions)})")
        for title, cash, npos in unpriced:
            lines.append(f"{title}: *value unknown* — {npos} position(s) unpriced, "
                         f"cash ${cash:,.0f}. NOT counted in the total below.")
        # Friend's fund: he trades it, not this engine, and the source gives
        # no position-level detail — folding it into `books` would force a
        # fake "cash $0 + $0 invested" next to a real equity number, which is
        # the exact kind of non-reconciling total the rest of this function
        # exists to prevent. Kept as its own line, own total, not summed in.
        ff = self._read_friend_fund()
        if ff:
            ff_eq = float(ff.get("investor_equity", 0) or 0)
            ff_nav = float(ff.get("current_nav", 0) or 0)
            ff_hwm = float(ff.get("high_water_mark", 0) or 0)
            stale = ""
            pulled_at = ff.get("pulled_at")
            if pulled_at:
                try:
                    age_h = (datetime.now(timezone.utc)
                              - datetime.fromisoformat(pulled_at)).total_seconds() / 3600
                    if age_h > 36:
                        stale = f"  ⚠️ stale ({age_h:.0f}h old — check external_fund_cron.log)"
                except ValueError:
                    pass
            lines.append(f"\n🤝 *Friend's fund* (external, he trades it): *${ff_eq:,.0f}*"
                         f"  (NAV ${ff_nav:,.0f}, HWM ${ff_hwm:,.0f}){stale}")
        te = sum(b[1] for b in books)
        tc = sum(b[2] for b in books)
        gross = sum(abs(float(p.get("qty", 0) or 0) * float(p.get("price", 0) or 0))
                    for b in books for p in b[3])
        verdict = ""
        if seed_total and not unpriced:
            d = te - seed_total
            word = "up" if d >= 0 else "down"
            verdict = f"  — *{word} ${abs(d):,.0f}* since the ${seed_total:,.0f} start"
        elif unpriced:
            # A total that silently omits a book is the §4.4 defect: $103,333 of
            # capital simply absent from the view. Say so rather than print a
            # smaller number as though it were the whole picture.
            verdict = "  — *incomplete*, a book could not be valued"
        # The footer is a DECOMPOSITION and has to add up, because a reader will
        # check it against the total — the previous version put gross exposure
        # here, where $27,717 cash + $20,391 exposure came to $48,108 against a
        # $40,475 total. Gross is stated separately, and only when shorts make it
        # differ from the invested figure, so it can never be read as a component.
        footer = f"(${tc:,.0f} cash + ${te - tc:,.0f} invested = ${te:,.0f})"
        if gross - (te - tc) > 1:
            footer += f"\n*${gross:,.0f} at risk* — gross exposure, shorts counted, not netted"
        lines.append(f"\n*Total: ${te:,.0f}*{verdict}\n{footer}")
        return "\n".join(lines)

    def _fmt_portfolio(self) -> str:
        s = self._read("state.json")
        comp = s.get("comparison") or {}
        lines = [f"⚡ *Trading book* — equity *${s.get('equity', 0):,.0f}*  "
                 f"cash ${s.get('cash', 0):,.0f}  ({s.get('mode', '?')} mode)"]
        for p in s.get("positions", [])[:15]:
            lines.append(f"  {p['symbol']}: {p['qty']:+.4f} @ ${p['avg_price']:,.2f} "
                         f"→ pnl ${p['pnl']:,.0f}")
        if not s.get("positions"):
            lines.append("  (no open positions)")
        if comp:
            lines.append(f"you vs formula-only: ${comp.get('input_value', 0):+,.0f}")
        total_cash = float(s.get("cash", 0) or 0)
        total_equity = float(s.get("equity", 0) or 0)

        # All five books, always. Reporting only two understated capital by
        # $103,333 and hid an event sleeve that had stopped trading. If a book
        # is idle that is information; silence is not.
        for icon, title, fname, empty in (
                ("🏛", "Investing book", "invest_state.json",
                 "no positions yet — theses awaiting your approval"),
                ("⚡", "Event sleeve", "event_state.json",
                 "no fresh shocks above threshold"),
                ("₿", "Crypto book", "crypto_state.json",
                 "flat — in cash"),
                ("⚡₿", "Crypto event sleeve", "crypto_event_state.json",
                 "no fresh crypto shocks above threshold"),
        ):
            blob = self._read(fname)
            book = blob.get("broker") if isinstance(blob.get("broker"), dict) else blob
            if not book:
                continue
            cash = float(book.get("cash", 0) or 0)
            total_cash += cash
            note = ""
            if fname == "crypto_state.json" and book.get("bear_mode"):
                note = "  🐻 bear mode"
            eq = blob.get("equity", book.get("equity"))
            head = f"equity *${float(eq):,.0f}*  cash ${cash:,.0f}" if eq is not None \
                else f"cash ${cash:,.0f}"
            total_equity += float(eq) if eq is not None else cash
            lines.append(f"\n{icon} *{title}* — {head}{note}")
            for p in (book.get("positions") or [])[:15]:
                direction = "long" if p["qty"] > 0 else "short"
                row = (f"  {p['symbol']}: {direction} {abs(p['qty']):.4f} "
                       f"@ ${p['avg_price']:,.2f}")
                if p.get("pnl") is not None:
                    row += f" → pnl ${p['pnl']:,.0f}"
                lines.append(row)
            if not book.get("positions"):
                lines.append(f"  ({empty})")

        # Equity is the headline, not cash. Short positions credit cash that is
        # still owed, so a cash total OVERSTATES the portfolio — it read $409k
        # against a real $400k. Cash is kept beside it because how much is
        # uncommitted still matters, but it must not be the number in bold.
        lines.append(f"\n💰 *total portfolio value* ${total_equity:,.0f}"
                     f"   (cash ${total_cash:,.0f})")
        return "\n".join(lines)

    def _fmt_news(self) -> str:
        from ai_investing.brain.store import BrainStore
        st = BrainStore(self.settings.brain.db_path)
        evs = st.recent_events(24, signal_only=False)[:12]
        stats = st.stats()
        st.close()
        if not evs:
            return "No events digested in the last 24h."
        lines = [f"📰 last 24h ({stats['articles']} articles remembered, digested once):"]
        for e in evs:
            tag = "🔇 NOISE" if e["is_noise"] else "📶"
            lines.append(f"{tag} {e['summary'][:110]} _(cred {e['credibility']:.0%}, {e['emotion']})_")
        return "\n".join(lines)

    def _fmt_simulate(self, headline: str) -> str:
        from ai_investing.brain import Brain
        out = Brain(self.settings).simulate(headline)
        ev = (out.get("events") or [{}])[0]
        top = ", ".join(f"{k} {v:+.2f}" for k, v in list(out.get("impacts", {}).items())[:8])
        assets = ", ".join(f"{k} {v['impact']:+.2f}" for k, v in out.get("asset_impacts", {}).items()) or "none"
        verdict = "NOISE — I would not trade this" if ev.get("is_noise") else \
            f"signal (credibility {ev.get('credibility', 0):.0%})"
        return (f"🧪 *{headline}*\nverdict: {verdict}\nripple: {top or 'no node matched'}\n"
                f"assets touched: {assets}")

    def _submit_news(self, text: str) -> str:
        """Queue a real news item for the engine's own next cycle. Unlike
        /simulate this WRITES to disk (data/news.py submit_user_news) and
        persists through the normal digest -> credibility -> graph path — but
        it only appends a file here; the actual digestion still happens inside
        the runner process, so two processes never touch brain state at once."""
        from ai_investing.data.news import submit_user_news
        try:
            rec = submit_user_news(self.settings, text)
        except ValueError:
            return "That looked empty — paste the text after /submit."
        poll_min = max(1, round(self.settings.poll_seconds / 60))
        return (f"📥 Queued for digestion: _{rec['title'][:160]}_\n\n"
                f"Goes through the real pipeline on the engine's next cycle "
                f"(~every {poll_min} min) — credibility-scored, ripples the graph, "
                f"sizes positions, remembered in brain.db. Trusted like a serious "
                f"outlet by default since you chose to send it, but it still has to "
                f"clear the same credibility bar as everything else. Check /news "
                f"after the next cycle to see how it landed.")

    def _apply_view(self, text: str) -> str:
        from ai_investing.strategy import UserViews
        from ai_investing.strategy import user_views as uv_mod
        v = UserViews.load(self.settings.user_views_path)
        parts = text.split()
        cmd = parts[0].lower()
        try:
            if cmd == "/view" and len(parts) > 1 and "=" in parts[1]:
                sym, _, val = parts[1].partition("=")
                v.views[sym.upper()] = max(-1.0, min(1.0, float(val)))
                msg = f"View set: {sym.upper()} = {v.views[sym.upper()]:+.2f}"
            elif cmd == "/block" and len(parts) > 1:
                if parts[1].upper() not in v.blocklist:
                    v.blocklist.append(parts[1].upper())
                msg = f"Blocked {parts[1].upper()} — any open position exits next cycle."
            elif cmd == "/unblock" and len(parts) > 1:
                if parts[1].upper() in v.blocklist:
                    v.blocklist.remove(parts[1].upper())
                msg = f"Unblocked {parts[1].upper()}."
            elif cmd == "/stance" and len(parts) > 1 and parts[1].lower() in uv_mod.STANCE_MULT:
                v.stance = parts[1].lower()
                msg = f"Stance: {v.stance}."
            else:
                return "Format: /view NVDA=0.5 · /block SYM · /unblock SYM · /stance cautious"
        except ValueError:
            return "Couldn't parse that value. Example: /view NVDA=0.5"
        v.save(self.settings.user_views_path)
        return f"✅ {msg}\n_(applies from the next engine cycle; safety limits still override)_"

    def _ask_llm(self, question: str) -> str:
        from ai_investing.data.news import _call_llm, llm_ready
        if not llm_ready(self.settings):
            return "No LLM reachable right now (start Ollama or set an API key). Commands still work: /help"
        prompt = _SYSTEM.format(context=self._context(), question=question[:500])
        out = _call_llm(prompt, self.settings, max_tokens=700, tier="fast")
        if not out:
            return "Hmm, my model didn't answer — try again or use /help commands."
        self.history.append((question, out))
        self.history = self.history[-6:]
        return out.strip()[:3900]

    def _register_commands(self) -> None:
        """Tell Telegram what commands exist so typing "/" shows them, the same
        popup BotFather's own commands produce. Cheap and idempotent — safe to
        call on every boot; Telegram just overwrites its stored list."""
        try:
            self._api("setMyCommands",
                      {"commands": json.dumps(
                          [{"command": c, "description": d} for c, d in self.COMMANDS])},
                      timeout=10)
        except Exception:
            pass   # the menu is a convenience; commands still work typed out in full

    # -- the loop --------------------------------------------------------------------
    def run_forever(self) -> None:
        # First outbound call of the process: at boot it ran before DNS was up and
        # killed the bot every time. The getUpdates loop below already survives a
        # blip; this handshake now does too. See ai_investing.net.
        from ai_investing.net import retry_transient
        me = retry_transient(lambda: self._api("getMe", {}, timeout=10),
                             what="telegram getMe")
        name = (me.get("result") or {}).get("username", "?")
        self._register_commands()
        print(f"Chat bot up as @{name} — talking only to chat {self.chat_id}. Ctrl-C to stop.")
        self._send("🧠 Chat is live — ask me anything about the brain, the book, or the trades.",
                   self.MENU)
        while True:
            try:
                upd = self._api("getUpdates", {"offset": self.offset + 1, "timeout": 50}, timeout=60)
            except Exception:
                import time
                time.sleep(5)
                continue
            for u in upd.get("result", []):
                self.offset = max(self.offset, u.get("update_id", 0))
                # tapped inline button
                cb = u.get("callback_query") or {}
                if cb:
                    sender = str((cb.get("from") or {}).get("id", ""))
                    data = (cb.get("data") or "")[:64]
                    try:
                        self._api("answerCallbackQuery", {"callback_query_id": cb.get("id", "")},
                                  timeout=10)
                    except Exception:
                        pass
                    if sender != self.chat_id or not data:
                        continue
                    print(f"  [chat:tap] {data}")
                    try:
                        reply, btns = self.handle_callback(data)
                        self._send(reply, btns)
                    except Exception as exc:
                        self._send(f"⚠️ that broke on my side: {type(exc).__name__}: {exc}")
                    continue
                msg = u.get("message") or {}
                text = (msg.get("text") or "").strip()
                sender = str((msg.get("chat") or {}).get("id", ""))
                if not text or sender != self.chat_id:
                    continue   # strangers and non-text are ignored silently
                print(f"  [chat] {text[:80]}")
                try:
                    reply, btns = self.handle(text)
                    self._send(reply, btns)
                except Exception as exc:
                    self._send(f"⚠️ that broke on my side: {type(exc).__name__}: {exc}")
            self._save_state()
