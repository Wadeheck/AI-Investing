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

# ------------------------------------------------------- the counting unit --
# WHY THIS EXISTS. `advice_log` is written EVERY CYCLE — ~126 rows/day at a
# ~10-minute cadence — and this module grades every one of them. So a single
# standing view ("long NVDA today") was frozen, graded and counted 126 separate
# times, against the same forward return, out of the same 5-day window. On
# 2026-08-21 the production table held 38,900 graded rows and **598** distinct
# (symbol, issue-day) observations: an inflation factor of 65x.
#
# Nothing downstream could see it. Two scorecard reviews reached OPPOSITE
# conclusions about the short side because both read the inflated n; every
# t-statistic derived from it was ~sqrt(65) = 8x too large; and
# `adviser_gate.THRESH["min_n"] = 500` — an anti-overfitting guard — was really
# a bar of 7.7 independent observations.
#
# Note this project had already solved the identical problem ONCE, on the other
# side of the same comparison: `adviser_gate._formula_short_stats` collapses
# 56,155 raw decision rows to 359 symbol-days and documents the choice of rule.
# The adviser's own side never got the same treatment. Same shape as §4.23 and
# §4.36 — a fix applied where the bug was observed and nowhere else.
#
# The fix keeps the ledger's promise (nothing is deleted, mistakes stay on the
# record) and adds the missing unit of account: every row is still written, and
# exactly one row per (issue-day, symbol) is flagged `is_primary`. Statistics
# read the primary rows; the audit trail keeps all of them.
#
# WHICH row is primary: the FIRST call of the day, by rowid. It is deterministic,
# it is the earliest point the view was actionable, it cannot be moved by
# re-issuing the same view later in the day, and it lets a row be graded as soon
# as it comes due instead of waiting for the day to close.

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


# Sector yardsticks, for ATTRIBUTION rather than grading — see
# `sector_benchmark_for`. Deliberately a separate table from `_BENCH`: that one
# feeds the live learning signal and is not disturbed here.
_SECTOR_BENCH = {
    # semis / big tech — the sleeve's dominant theme
    "NVDA": "XLK", "AMD": "XLK", "ASML": "XLK", "TSM": "XLK", "INTC": "XLK",
    "MU": "XLK", "AVGO": "XLK", "MRVL": "XLK", "SMCI": "XLK", "QCOM": "XLK",
    "000660.KS": "XLK", "005930.KS": "XLK", "2330.TW": "XLK",
    # solar: the stock against the solar ETF, never against the broad market
    "JKS": "TAN", "FSLR": "TAN", "ENPH": "TAN", "SEDG": "TAN",
    # financials
    "JPM": "XLF", "BAC": "XLF", "GS": "XLF", "C": "XLF", "WFC": "XLF",
    # energy names against the energy ETF
    "XOM": "XLE", "CVX": "XLE", "COP": "XLE", "SLB": "XLE",
}


def sector_benchmark_for(symbol: str) -> tuple[str | None, str]:
    """The yardstick for ATTRIBUTING a realised trade, and how confident it is.

    WHY THIS IS SEPARATE FROM `benchmark_for`. That function feeds the live
    learning signal (`event_outcomes.excess_ret`), and changing it would
    silently re-grade history. This one is additive and read-only: it exists so
    `brain_audit --section pnl` can ask a HARDER question than "did the trade
    beat SPY".

    THE RULE, and it is the substance:

      A SECTOR OR THEMATIC ETF held outright (`XLE`, `TAN`, `USO`) is measured
      against the BROAD market. Buying the energy ETF *is* the sector call, so
      the sector move is the thing being judged, not a factor to strip out.

      A SINGLE STOCK is measured against its SECTOR. NVDA up 6% in a week when
      XLK is up 5% is not a 6% insight — it is a 1% one. Benchmarking it
      against SPY credits semiconductor beta as skill, which is exactly how a
      long book in a rising sector looks talented (§4.6, §4.57).

    Returns `(benchmark, confidence)` where confidence is "sector" when a real
    sector yardstick was found and "broad" when it fell back — so a caller can
    report how much of its sample got the harder test rather than assuming all
    of it did.
    """
    sym = (symbol or "").upper()
    if sym in BENCH_SYMBOLS:
        return None, "self"
    b = _SECTOR_BENCH.get(sym)
    if b:
        return b, "sector"
    return benchmark_for(sym), "broad"


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
                    "ALTER TABLE advice_outcomes ADD COLUMN basis TEXT",
                    "ALTER TABLE advice_outcomes ADD COLUMN is_conviction INTEGER",
                    # v6: the counting unit (see the module header). issue_date is
                    # the SGT calendar day the call was issued — the same day-key
                    # the rest of this module uses; is_primary marks the one row
                    # per (issue_date, symbol) that statistics may count.
                    "ALTER TABLE advice_outcomes ADD COLUMN issue_date TEXT",
                    "ALTER TABLE advice_outcomes ADD COLUMN is_primary INTEGER"):
            try:
                self.conn.execute(ddl)
            except sqlite3.OperationalError:
                pass
        self.conn.execute("UPDATE advice_outcomes SET basis='absolute' WHERE basis IS NULL")
        self._backfill_primary()
        self.conn.commit()
        self.rel_path = os.path.join(data_dir, "reliability.json")

    def _backfill_primary(self) -> None:
        """One-time: label the 42,674 rows written before the counting unit
        existed. Rows are never deleted or re-graded — only labelled."""
        if not self.conn.execute(
                "SELECT 1 FROM advice_outcomes WHERE issue_date IS NULL LIMIT 1").fetchone():
            return
        # SGT day, matching _today_sgt() and score_due()'s issue_date.
        self.conn.execute(
            "UPDATE advice_outcomes SET issue_date = date(ts_issued, '+8 hours') "
            "WHERE issue_date IS NULL")
        self.conn.execute("""
            UPDATE advice_outcomes SET is_primary = 0 WHERE is_primary IS NULL""")
        self.conn.execute("""
            UPDATE advice_outcomes SET is_primary = 1 WHERE rowid IN (
                SELECT MIN(rowid) FROM advice_outcomes GROUP BY issue_date, symbol)""")
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_outcomes_day "
            "ON advice_outcomes(issue_date, symbol)")
        n = self.conn.execute(
            "SELECT COUNT(*), SUM(is_primary) FROM advice_outcomes").fetchone()
        print(f"  scorecard: labelled the counting unit — {n[0]} graded rows collapse "
              f"to {n[1]} distinct (day, symbol) observations "
              f"({(n[0] / n[1]) if n[1] else 0:.1f}x replication, now excluded from stats)")

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
                adv = json.loads(blob) or {}
            except json.JSONDecodeError:
                continue
            # Grade the WATCH list as well. It was never scored, so the only calls
            # ever measured were the ones that cleared the conviction floor — and
            # from 2026-08-04 the watch list is what guarantees >=10 stock and >=10
            # crypto data points a round. An ungraded prediction teaches nothing.
            # `conviction` keeps the two tiers separable so filler cannot flatter
            # or depress the number that matters.
            trades = [dict(t, _conv=True) for t in (adv.get("trades") or [])]
            trades += [dict(t, _conv=bool(t.get("conviction")))
                       for t in (adv.get("watch") or [])]
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

                # The counting unit (module header): every row is written, but
                # only the FIRST row per (issue_date, symbol) may be counted.
                is_primary = int(not self.conn.execute(
                    "SELECT 1 FROM advice_outcomes WHERE issue_date=? AND symbol=? LIMIT 1",
                    (issue_date, sym)).fetchone())

                hit = verdict(direction, ret, excess)
                # absolute verdict kept alongside, so "did it go up" stays visible
                hit_abs = None
                if abs(ret) >= DEADBAND:
                    hit_abs = int((direction == "long") == (ret > 0))
                basis = "excess" if excess is not None else "absolute"

                self.conn.execute(
                    "INSERT INTO advice_outcomes"
                    "(advice_id,symbol,direction,ts_issued,horizon_days,realized_ret,hit,"
                    " scored_at,bench_symbol,bench_ret,excess_ret,hit_abs,basis,"
                    " is_conviction,issue_date,is_primary)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (aid, sym, direction, ts, horizon_days, round(ret, 5), hit, now,
                     bench, None if bench_ret is None else round(bench_ret, 5),
                     None if excess is None else round(excess, 5), hit_abs, basis,
                     int(bool(t.get("_conv"))), issue_date, is_primary))
                out.append({"symbol": sym, "direction": direction, "ret": ret, "hit": hit,
                            "bench": bench, "bench_ret": bench_ret, "excess": excess,
                            "hit_abs": hit_abs, "basis": basis,
                            "conviction": bool(t.get("_conv")),
                            "primary": bool(is_primary)})
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
        """EMA per-symbol trust from scored outcomes. Returns plain-language changes.

        ONE STEP PER (symbol, day) — see the module header on the counting unit.
        This loop used to step once per outcome ROW, and rows arrived ~65x per
        symbol-day, so the EMA took 65 steps a day and retained 0.88^65 = 0.00026
        of yesterday. That is not an exponential moving average; it is a same-day
        step function that slams to R_MIN or R_MAX on the latest result. It
        showed: on 2026-08-21, 56 of 122 symbols (46%) sat pinned at a bound, and
        NVDA — a name the sleeve trades profitably and the graph reaches over 572
        paths — carried r=0.506, one step off the floor, multiplying the adviser's
        conviction on it by half.

        With alpha=0.12 and one step per day, r now has a ~5-6 day half-life:
        long enough to hold a view, short enough to change one.
        """
        try:
            with open(self.rel_path) as fh:
                rel = json.load(fh)
        except (OSError, json.JSONDecodeError):
            rel = {}
        notes = []
        for o in outcomes:
            if o["hit"] is None:
                continue
            if not o.get("primary", True):
                continue          # a re-issue of a view already counted today
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
            "       COALESCE(basis,'absolute'), COALESCE(is_conviction,1) "
            "FROM advice_outcomes WHERE scored_at >= ? AND hit IS NOT NULL "
            # one observation per (day, symbol) — see the module header. Without
            # this every n here was ~65x the real sample.
            "  AND COALESCE(is_primary,1)=1",
            (cutoff,)).fetchall()

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
                                "avoid": rate(lambda r: r[6] == "excess" and r[1] == "avoid"),
                                # what it would ACT on vs the coverage calls that
                                # exist only to produce data points. Mixing them
                                # would let filler flatter or depress the number
                                # that actually decides trades.
                                "conviction": rate(lambda r: r[6] == "excess" and r[7]),
                                "coverage": rate(lambda r: r[6] == "excess" and not r[7])},
            "by_class": {
                "stock": rate(lambda r: r[6] == "excess" and "/" not in r[0]),
                "crypto": rate(lambda r: r[6] == "excess" and "/" in r[0])},
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
