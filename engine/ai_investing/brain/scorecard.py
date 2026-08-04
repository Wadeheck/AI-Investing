"""The scorecard: every recommendation is kept, cross-checked, and learned from.

Three jobs, run daily:

  1. SNAPSHOT — store today's prices (already fetched by the cycle, so free).
  2. SCORE — every advice list ever issued is frozen in advice_log; once a
     call is `horizon` days old, compare its direction against the realized
     price move and freeze the outcome in advice_outcomes. Nothing is ever
     deleted or rewritten — mistakes stay on the record.
  3. LEARN — outcomes update a per-symbol reliability weight r ∈ [0.5, 1.4]
     (EMA: hits push trust up, misses push it down). The adviser multiplies
     its field-driven conviction by r, so symbols where the brain's causal
     map keeps being wrong get listened to less — a real mathematical weight
     updated by evidence, not vibes.

The daily overview reports the running hit-rate and what was just learned,
so the learning is visible, not silent.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

HORIZON_DAYS = 5           # a directional call is judged against the move over ~a week
DEADBAND = 0.003           # |move| under 0.3% is noise — excluded, not claimed
R_MIN, R_MAX, R_ALPHA = 0.5, 1.4, 0.12

# --------------------------------------------------------------- benchmarks --
# WHY THIS EXISTS. Until 2026-08-04 a call was graded on its ABSOLUTE move, and
# `short_or_avoid` was graded as if it had predicted a fall:
#
#     hit = 1 if ((direction == "long") == (ret > 0)) else 0
#
# But "avoid" does not claim a fall. It claims UNDERPERFORMANCE. Grading it as a
# fall in a rising tape marks every correct avoid as a miss, and that is exactly
# what the record showed:
#
#     long             n=93  hit 0.505   avg realised +3.3%
#     short_or_avoid   n=77  hit 0.182   avg realised +3.6%   <-- market rose
#
# The 0.182 was not a skill deficit; it was a category error. A blended 0.404
# "hit rate" sat unexplained in the docs for days because of it. So: a benchmark,
# and each label graded on what it actually claimed.
_BENCH = {
    "US": "SPY", "HK": "2800.HK", "SG": "ES3.SI", "CN": "2800.HK",
    "JP": "EWJ", "KR": "EWY", "TW": "EWY", "IN": "INDA", "EU": "VGK",
    "CRYPTO": "BTC/USD",
}
BENCH_SYMBOLS = tuple(sorted(set(_BENCH.values())))


def benchmark_for(symbol: str, market: str | None = None) -> str | None:
    """The yardstick a call is measured against.

    Crypto is measured against BTC, never SPY: judging ETH's dollar move against
    an equity index says nothing about whether the call had insight. A coin that
    rose 4% on a day BTC rose 9% was a bad long, and no equity benchmark can see
    that.

    A benchmark is never scored against itself — SPY vs SPY is a tautology, and
    would quietly inject guaranteed-zero excess rows into the learning signal.
    """
    if symbol in BENCH_SYMBOLS:
        return None
    if "/" in symbol:                      # BTC/USD, ETH/USD, ...
        return None if symbol == _BENCH["CRYPTO"] else _BENCH["CRYPTO"]
    if market and market.upper() in _BENCH:
        return _BENCH[market.upper()]
    if "." in symbol:                      # 0700.HK, D05.SI, 9984.T ...
        suffix = symbol.rsplit(".", 1)[-1].upper()
        return {"HK": _BENCH["HK"], "SI": _BENCH["SG"], "SS": _BENCH["CN"],
                "SZ": _BENCH["CN"], "T": _BENCH["JP"], "KS": _BENCH["KR"],
                "TW": _BENCH["TW"], "PA": _BENCH["EU"], "DE": _BENCH["EU"],
                "AS": _BENCH["EU"]}.get(suffix, _BENCH["US"])
    return _BENCH["US"]


def verdict(direction: str, ret: float, excess: float | None) -> int | None:
    """Did the call come true? 1 hit / 0 miss / None = not claimable.

    One meaning per label, which is the whole point:

      long   — "this will beat the market."     hit when excess > 0
      avoid  — "this will lag the market."      hit when excess < 0
      short  — "this will FALL."                hit when the absolute move is down

    `avoid` is deliberately NOT graded on a fall. Nothing in this system shorts
    stocks (both paper venues refuse it, and shorts have failed six independent
    tests here), so a negative call is advice to stay out — and staying out of
    something that rose 2% while the market rose 6% was correct.
    """
    if direction == "short":
        return None if abs(ret) < DEADBAND else int(ret < 0)
    if excess is None:
        return None                       # no benchmark ⇒ nothing to claim
    if abs(excess) < DEADBAND:
        return None                       # inside the noise band, not a result
    return int(excess > 0) if direction == "long" else int(excess < 0)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS price_history (
  date TEXT NOT NULL, symbol TEXT NOT NULL, price REAL NOT NULL,
  PRIMARY KEY (date, symbol));
CREATE TABLE IF NOT EXISTS advice_outcomes (
  advice_id INTEGER NOT NULL, symbol TEXT NOT NULL, direction TEXT NOT NULL,
  ts_issued TEXT NOT NULL, horizon_days INTEGER NOT NULL,
  realized_ret REAL, hit INTEGER,          -- 1 hit / 0 miss / NULL excluded (deadband)
  scored_at TEXT NOT NULL,
  PRIMARY KEY (advice_id, symbol));
"""


def _today_sgt() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=8)).date().isoformat()


class Scorecard:
    def __init__(self, settings):
        self.settings = settings
        data_dir = os.path.dirname(os.path.abspath(settings.state_path))
        self.conn = sqlite3.connect(os.path.join(data_dir, "brain.db"))
        self.conn.executescript(_SCHEMA)
        try:    # migration: daily volume rides the same snapshot (v4 upgrade)
            self.conn.execute("ALTER TABLE price_history ADD COLUMN volume REAL")
        except sqlite3.OperationalError:
            pass                     # column already exists
        # v5: benchmark-relative grading. New columns rather than a rewrite —
        # the 170 rows already scored under the absolute rule keep their verdicts
        # and are tagged `basis='absolute'`, so the two eras can be reported
        # separately instead of being blended into one meaningless average.
        for ddl in ("ALTER TABLE advice_outcomes ADD COLUMN bench_symbol TEXT",
                    "ALTER TABLE advice_outcomes ADD COLUMN bench_ret REAL",
                    "ALTER TABLE advice_outcomes ADD COLUMN excess_ret REAL",
                    "ALTER TABLE advice_outcomes ADD COLUMN hit_abs INTEGER",
                    "ALTER TABLE advice_outcomes ADD COLUMN basis TEXT"):
            try:
                self.conn.execute(ddl)
            except sqlite3.OperationalError:
                pass
        self.conn.execute("UPDATE advice_outcomes SET basis='absolute' WHERE basis IS NULL")
        self.conn.commit()
        self.rel_path = os.path.join(data_dir, "reliability.json")

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------- snapshot --
    def snapshot_prices(self, prices_by_symbol: dict[str, float],
                        volumes_by_symbol: dict[str, float] | None = None) -> None:
        d = _today_sgt()
        vols = volumes_by_symbol or {}
        self.conn.executemany(
            "INSERT OR REPLACE INTO price_history(date,symbol,price,volume) VALUES(?,?,?,?)",
            [(d, s, p, vols.get(s) or None) for s, p in prices_by_symbol.items() if p > 0])
        self.conn.commit()

    def day_moves(self, prices_by_symbol: dict[str, float]) -> dict[str, float]:
        """1-day % moves vs the last stored snapshot — the daily price pulse fed
        into the web. Empty once today's snapshot exists (one pulse per day)."""
        row = self.conn.execute("SELECT MAX(date) FROM price_history").fetchone()
        last = row[0] if row else None
        if not last or last >= _today_sgt():
            return {}
        out: dict[str, float] = {}
        for sym, px in prices_by_symbol.items():
            if px <= 0:
                continue
            prev = self.conn.execute(
                "SELECT price FROM price_history WHERE symbol=? AND date=?",
                (sym, last)).fetchone()
            if prev and prev[0] > 0:
                r = px / prev[0] - 1.0
                if abs(r) >= 0.01:
                    out[sym] = round(r, 4)
        return out

    def _price_near(self, symbol: str, date: str, latest: bool = False) -> float | None:
        q = ("SELECT price FROM price_history WHERE symbol=? ORDER BY date DESC LIMIT 1"
             if latest else
             "SELECT price FROM price_history WHERE symbol=? AND date>=? ORDER BY date ASC LIMIT 1")
        row = self.conn.execute(q, (symbol,) if latest else (symbol, date)).fetchone()
        return row[0] if row else None

    # ---------------------------------------------------------------- score --
    def score_due(self, horizon_days: int = HORIZON_DAYS) -> list[dict]:
        """Score every advice call at least `horizon_days` old and not yet scored."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=horizon_days)).isoformat()
        rows = self.conn.execute(
            # advice_log is declared as (ts, advice) with no explicit id column,
            # so `SELECT id` raised OperationalError on EVERY cycle and the whole
            # scoring pass was swallowed by its caller's except. 195 advice lists
            # were logged and none were ever graded. sqlite's implicit rowid is
            # the stable key advice_outcomes.advice_id already refers to.
            "SELECT rowid AS id, ts, advice FROM advice_log WHERE ts <= ? ORDER BY rowid",
            (cutoff,)).fetchall()
        out: list[dict] = []
        now = datetime.now(timezone.utc).isoformat()
        for aid, ts, blob in rows:
            try:
                trades = (json.loads(blob) or {}).get("trades") or []
            except json.JSONDecodeError:
                continue
            issue_date = (datetime.fromisoformat(ts) + timedelta(hours=8)).date().isoformat()
            for t in trades:
                sym, direction = t.get("symbol"), t.get("direction")
                if not sym or not direction:
                    continue
                if self.conn.execute("SELECT 1 FROM advice_outcomes WHERE advice_id=? AND symbol=?",
                                     (aid, sym)).fetchone():
                    continue
                p0 = self._price_near(sym, issue_date)
                p1 = self._price_near(sym, issue_date, latest=True)
                if not p0 or not p1:
                    continue                      # price snapshots start today; old calls stay unscored
                ret = p1 / p0 - 1.0

                # the market over the SAME window, from the same snapshots
                bench = benchmark_for(sym, t.get("market"))
                b0 = self._price_near(bench, issue_date) if bench else None
                b1 = self._price_near(bench, issue_date, latest=True) if bench else None
                bench_ret = (b1 / b0 - 1.0) if (b0 and b1) else None
                excess = (ret - bench_ret) if bench_ret is not None else None

                hit = verdict(direction, ret, excess)
                # absolute verdict kept alongside, so "did it go up" stays visible
                hit_abs = None
                if abs(ret) >= DEADBAND:
                    hit_abs = int((direction == "long") == (ret > 0))
                basis = "excess" if excess is not None else "absolute"

                self.conn.execute(
                    "INSERT INTO advice_outcomes"
                    "(advice_id,symbol,direction,ts_issued,horizon_days,realized_ret,hit,"
                    " scored_at,bench_symbol,bench_ret,excess_ret,hit_abs,basis)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (aid, sym, direction, ts, horizon_days, round(ret, 5), hit, now,
                     bench, None if bench_ret is None else round(bench_ret, 5),
                     None if excess is None else round(excess, 5), hit_abs, basis))
                out.append({"symbol": sym, "direction": direction, "ret": ret, "hit": hit,
                            "bench": bench, "bench_ret": bench_ret, "excess": excess,
                            "hit_abs": hit_abs, "basis": basis})
        self.conn.commit()
        # A benchmark with no price history silently downgrades every call in that
        # market back to absolute grading — the exact failure this change exists to
        # remove, reappearing as a missing row instead of a wrong formula. Say so
        # loudly; the fix is to add the benchmark to the watchlist so the cycle
        # snapshots it (SPY was missing when this was written, which would have
        # made the whole thing a no-op for US names).
        missing = sorted({o["bench"] for o in out
                          if o["bench"] and o["bench_ret"] is None})
        if missing:
            print(f"  !! scorecard: no price history for benchmark(s) {', '.join(missing)} "
                  f"— those calls fell back to ABSOLUTE grading. Add them to the "
                  f"watchlist so the cycle snapshots them.")
        return out

    # ---------------------------------------------------------------- learn --
    def update_reliability(self, outcomes: list[dict]) -> list[str]:
        """EMA per-symbol trust from scored outcomes. Returns plain-language changes."""
        try:
            with open(self.rel_path) as fh:
                rel = json.load(fh)
        except (OSError, json.JSONDecodeError):
            rel = {}
        notes = []
        for o in outcomes:
            if o["hit"] is None:
                continue
            r = rel.get(o["symbol"], {}).get("r", 1.0)
            n = rel.get(o["symbol"], {}).get("n", 0)
            target = R_MAX if o["hit"] else R_MIN
            new_r = round(min(R_MAX, max(R_MIN, r + R_ALPHA * (target - r))), 3)
            rel[o["symbol"]] = {"r": new_r, "n": n + 1}
            if abs(new_r - r) >= 0.02:
                # report the number the verdict was actually based on, not the
                # absolute move — otherwise a "missed" note can show a gain and
                # look like a bug in the learning rather than a market comparison
                ex = o.get("excess")
                basis = (f"{ex:+.1%} vs {o.get('bench') or 'market'}"
                         if ex is not None else f"{o['ret']:+.1%}")
                notes.append(f"{'raised' if new_r > r else 'trimmed'} trust in {o['symbol']} "
                             f"calls to ×{new_r:.2f} ({'hit' if o['hit'] else 'missed'} "
                             f"{basis})")
        if notes:
            try:
                with open(self.rel_path, "w") as fh:
                    json.dump(rel, fh, indent=1)
            except OSError:
                pass
        return notes

    # --------------------------------------------------------------- report --
    def track_record(self, days: int = 30) -> dict:
        """The record, split by grading basis and by direction.

        NOT one blended hit rate. Blending is what produced the meaningless 0.404:
        it averaged `long` calls graded on absolute moves with `avoid` calls graded
        as if they were shorts, in a rising market. A single number that mixes two
        different questions cannot be improved because it cannot be interpreted.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = self.conn.execute(
            "SELECT symbol, direction, realized_ret, hit, excess_ret, bench_symbol, "
            "       COALESCE(basis,'absolute') FROM advice_outcomes "
            "WHERE scored_at >= ? AND hit IS NOT NULL", (cutoff,)).fetchall()

        def rate(sel):
            g = [r for r in rows if sel(r)]
            return {"n": len(g),
                    "hit_rate": round(sum(r[3] for r in g) / len(g), 3) if g else None}

        cur = [r for r in rows if r[6] == "excess"]
        # edge of the call: excess for market-relative rows, signed move otherwise
        edge = lambda r: ((r[4] if r[4] is not None else r[2])
                          * (1 if r[1] == "long" else -1))
        best = max(cur or rows, key=edge, default=None)
        worst = min(cur or rows, key=edge, default=None)

        def fmt(r):
            if r is None:
                return None
            side = "long" if r[1] == "long" else "against"
            if r[4] is not None:
                return f"{side} {r[0]} ({r[4]:+.1%} vs {r[5]})"
            return f"{side} {r[0]} ({r[2]:+.1%} absolute)"

        return {
            "total": len(rows),
            "hits": sum(r[3] for r in rows),
            "hit_rate": round(sum(r[3] for r in rows) / len(rows), 3) if rows else None,
            # the numbers worth reading
            "market_relative": {**rate(lambda r: r[6] == "excess"),
                                "long": rate(lambda r: r[6] == "excess" and r[1] == "long"),
                                "avoid": rate(lambda r: r[6] == "excess" and r[1] == "avoid")},
            # the pre-2026-08-04 era, kept visible and kept separate
            "legacy_absolute": rate(lambda r: r[6] == "absolute"),
            "best": fmt(best),
            "worst": fmt(worst),
        }


def reliability_weights(settings) -> dict[str, float]:
    """{symbol: r} for the adviser — 1.0 where nothing has been learned yet."""
    path = os.path.join(os.path.dirname(os.path.abspath(settings.state_path)),
                        "reliability.json")
    try:
        with open(path) as fh:
            return {s: v.get("r", 1.0) for s, v in json.load(fh).items()}
    except (OSError, json.JSONDecodeError):
        return {}
