"""The learning spine — one coherent learner for an unattended system.

Design and rationale: docs/design/LEARNING.md. In brief:

  every decision writes a CLAIM        (policy, driver, regime, expected move)
  every exit settles it                (direction, calibration, cost-aware)
  skill is a POSTERIOR, not an average (uncertainty governs how much it moves)
  skill is CONDITIONAL on regime       (good in calm, bad in panic is useful)
  capital follows demonstrated skill   (weekly, bounded, rate-limited)
  the learner defends itself           (drift + regime-break detection)

The hard rule this module obeys: the fast loop may adjust SIZING and
EXPECTATIONS; it may never change structure. Structure changes only through
the offline walk-forward gauntlet. A live system that rewrites its own rules
from a handful of trades destroys itself.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta, timezone

# --- learning constants (documented in docs/design/LEARNING.md §4, §6) -------------
N_HALF = 12.0             # sample count at which evidence carries half weight
EDGE_GAIN = 0.8           # how hard proven edge moves size
SIZE_BOUNDS = (0.5, 1.4)  # a bad policy shrinks; a good one cannot run away
GAIN_BOUNDS = (0.25, 3.0)  # expectation-scaling limits
RATIO_CLIP = 3.0          # one freak outcome must not rewrite the SCORE
# MAGNITUDE is a separate question from score, and needs a separate bound.
#
# RATIO_CLIP exists so a single freak outcome cannot dominate the direction
# penalty, and for that job 3.0 is right — beyond it the penalty has already
# reached its floor, so more range buys nothing. But `calibration_gain` reads
# the same number to answer "how far off is expected_move", and there 3.0
# destroys the signal it needs. Measured on the live record 2026-08-21:
#
#     settled claims                        19
#     clipped at +/-3.0                     15  (79%)
#     median |true ratio|                 14.4
#     max                                106.4   (000660.KS: exp 0.11%, real 11.4%)
#
# expected_move is systematically one to two ORDERS OF MAGNITUDE too small, and
# every observation that says so was recorded as "3.0".
MAG_CLIP = 50.0           # magnitude evidence: wide enough to see, bounded enough to survive
# Severity of a loss, on top of the direction/conviction penalty. Referenced to the
# risk budget: a loss that used the whole per-position allowance is the worst case
# the design permits, so it earns the full extra cost and no more.
SEVERITY_REF = 0.10       # fallback budget when risk config is unavailable
SEVERITY_WEIGHT = 0.25    # max extra penalty; keeps score within [-1, 1]
HIT_FRACTION = 0.5        # realized must reach this share of expected to score +1
COST_FLOOR = 0.002        # a "win" inside 20bps of frictions is noise, not skill
REGIME_MIN_N = 15         # samples before a regime-specific posterior is used
BUDGET_BOUNDS = (0.10, 0.50)
BUDGET_STEP = 0.05        # max weekly reallocation per policy
DRIFT_WINDOW = 20         # recent trades compared against the long run
DRIFT_Z = 2.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def regime_of(risk_appetite: float | None, bear: bool = False) -> str:
    """Three states is enough: more slices means fewer samples per slice."""
    if bear:
        return "risk_off"
    if risk_appetite is None:
        return "neutral"
    if risk_appetite <= -0.2:
        return "risk_off"
    if risk_appetite >= 0.2:
        return "risk_on"
    return "neutral"


class LearningSpine:
    def __init__(self, settings):
        d = os.path.dirname(os.path.abspath(settings.state_path))
        self.ledger_path = os.path.join(d, "expectations.jsonl")
        self.path = os.path.join(d, "learning_state.json")
        # The per-position risk allowance, so a loss can be scored against what the
        # design actually permits rather than a constant guessed here.
        self.loss_budget = abs(float(
            getattr(getattr(settings, "risk", None), "max_loss_per_position", 0.0)
            or SEVERITY_REF))
        self._s = self._load()

    # -- persistence ---------------------------------------------------------
    def _load(self) -> dict:
        try:
            with open(self.path) as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            return {"policies": {}, "drivers": {}, "open": {}, "budgets": {}}

    def _save(self) -> None:
        try:
            with open(self.path, "w") as fh:
                json.dump(self._s, fh, indent=1)
        except OSError:
            pass

    def _append(self, row: dict) -> None:
        try:
            with open(self.ledger_path, "a") as fh:
                fh.write(json.dumps(row) + "\n")
        except OSError:
            pass

    # -- the claim -----------------------------------------------------------
    @staticmethod
    def expected_move(signal: float, vol_daily: float, horizon_days: int,
                      gain: float = 1.0) -> float:
        """The engine's own scale law: |impact| x vol x sqrt(h) x gain."""
        return abs(signal) * max(1e-6, vol_daily) * math.sqrt(max(1, horizon_days)) * gain

    def record(self, policy: str, symbol: str, direction: int, signal: float,
               vol_daily: float, horizon_days: int, regime: str = "neutral",
               driver: str = "", notional: float = 0.0) -> str:
        gain = self.calibration_gain(policy)
        exp = self.expected_move(signal, vol_daily, horizon_days, gain)
        tid = f"{policy}:{symbol}:{_now().isoformat()}"
        # Refuse BEFORE writing anything. The first version appended the "open" row
        # and only then checked, leaving a refused claim recorded as open — the same
        # dangling-record corruption the check exists to prevent.
        book = self._s.setdefault("open", {})
        key = f"{policy}:{symbol}"
        if key in book:
            self._append({"id": tid, "ts": _now().isoformat(), "state": "rejected",
                          "policy": policy, "symbol": symbol,
                          "reason": "already-open claim on this policy:symbol",
                          "kept": book[key].get("id")})
            print(f"  !! spine: {key} already has an open claim "
                  f"({book[key].get('id')}) — new claim NOT opened. A position was "
                  f"added to a symbol the ledger is still tracking.")
            self._save()
            return book[key].get("id") or tid
        self._append({"id": tid, "ts": _now().isoformat(), "state": "open",
                      "policy": policy, "symbol": symbol, "direction": int(direction),
                      "signal": round(float(signal), 4), "regime": regime,
                      "vol_daily": round(float(vol_daily), 5),
                      "horizon_days": int(horizon_days), "driver": driver,
                      "notional": round(float(notional), 2),
                      "expected_move": round(exp, 5), "gain_used": round(gain, 3)})
        # ONE OPEN CLAIM PER policy:symbol (checked above, before any write). A second
        # claim on a live symbol used to REPLACE the first, which was then never
        # settled and sat in expectations.jsonl as a permanently dangling `open`
        # record. It happened for real on 2026-08-04: the event sleeve's broken
        # re-entry guard opened two USO claims 44 minutes apart and one vanished, so
        # the corpus is missing a resolution it will never get. That corpus is the one
        # artefact here that cannot be rebuilt, so corrupting it must be loud. The
        # FIRST claim survives: the position was opened on it, and its expected_move
        # is what the exit gets judged against.
        book[key] = {
            "id": tid, "expected_move": exp, "direction": int(direction),
            "driver": driver, "regime": regime, "signal": abs(float(signal))}
        self._save()
        return tid

    # -- the outcome ---------------------------------------------------------
    def settle(self, policy: str, symbol: str, realized_move: float,
               held_days: int = 0, exit_reason: str = "",
               cost_frac: float = COST_FLOOR) -> dict | None:
        claim = (self._s.get("open") or {}).pop(f"{policy}:{symbol}", None)
        if not claim:
            return None
        exp = max(1e-6, float(claim["expected_move"]))
        signed = realized_move * (1 if claim["direction"] > 0 else -1)
        ratio_true = signed / exp
        ratio = max(-RATIO_CLIP, min(RATIO_CLIP, ratio_true))

        # SCORE (docs/design/LEARNING.md §3): direction is the only true mistake, and
        # conviction makes being wrong worse. Costs must be cleared to count.
        conviction = max(0.2, min(1.0, float(claim.get("signal", 0.2)) * 5))
        if signed <= -cost_frac:
            score = -min(1.0, 0.5 + 0.5 * conviction)     # confidently wrong hurts more
            # SEVERITY. Direction is the primary mistake and stays the dominant term,
            # but the old score was blind to HOW wrong: a -10% stop-out and a -0.3%
            # scratch scored identically at equal conviction. For a system whose hard
            # rule is "no position may lose more than max_loss_per_position", failing
            # to distinguish a full stop-out from a nick is a real blind spot — it
            # was the actual USO outcome on 2026-08-04 (expected +0.31%, realised
            # -10.06%) scoring the same as a trade that lost a fifth of a percent.
            #
            # Scaled by the clipped ratio, which is already bounded, so one freak
            # outcome still cannot rewrite the model. At |ratio| >= RATIO_CLIP the
            # penalty reaches its floor of -1.0 and stops — bounded, not unbounded.
            # Measured on the ABSOLUTE loss against the risk budget, NOT on the
            # ratio to expectation. Ratio was the first attempt and it broke the
            # design contract: expected_move scales with conviction, so a confident
            # call losing X has a SMALLER ratio than a tentative one losing the same
            # X, and severity then cancelled out the conviction penalty it is
            # supposed to add to. Conviction stays the dominant term; severity is a
            # bounded additive cost on top.
            severity = min(1.0, abs(signed) / max(1e-6, self.loss_budget))
            score = max(-1.0, score - SEVERITY_WEIGHT * severity)
        elif signed >= max(cost_frac, HIT_FRACTION * exp):
            score = 1.0
        else:
            score = 0.0                                    # right but inside the noise
        won = signed > cost_frac

        out = {"id": claim["id"], "ts": _now().isoformat(), "state": "settled",
               "policy": policy, "symbol": symbol, "regime": claim.get("regime", "neutral"),
               "expected_move": round(exp, 5), "realized_move": round(signed, 5),
               "ratio": round(ratio, 3),
               # the UNCLIPPED ratio, so the record shows how far off the
               # expectation really was. §4A carried "RATIO_CLIP hides severity
               # beyond 3x" for exactly this: 15 of 19 settled claims recorded
               # a magnitude of "3.0" for true ratios spanning 4.8 to 106.
               "ratio_true": round(ratio_true, 3),
               "ratio_clipped": abs(ratio_true) > RATIO_CLIP,
               "score": round(score, 3), "won": won,
               "held_days": held_days, "exit_reason": exit_reason,
               "driver": claim.get("driver", "")}
        opened = claim["id"].split(":", 2)[-1]
        if self._gap_affected(opened):
            out["gap_affected"] = True         # journalled, but NOT learned from
            self._append(out)
            self._save()
            return out
        self._append(out)
        self._update(policy, claim.get("driver", ""), claim.get("regime", "neutral"),
                     ratio, score, won, ratio_true)
        self._save()
        return out

    def _gap_affected(self, opened_iso: str) -> bool:
        """True if an outage overlapped this trade's life. A stop that fired
        late because the engine was down says nothing about the SIGNAL, so it
        must not move the posteriors."""
        try:
            gp = os.path.join(os.path.dirname(self.path), "learning_gaps.json")
            with open(gp) as fh:
                wins = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return False
        for w in wins[-50:]:
            if opened_iso <= w.get("end", "") and w.get("start", "") <= _now().isoformat():
                return True
        return False

    def _bucket(self, scope: str, key: str) -> dict:
        return self._s.setdefault(scope, {}).setdefault(
            key, {"n": 0, "wins": 0, "ratio": None, "score": None, "recent": []})

    def _update(self, policy: str, driver: str, regime: str,
                ratio: float, score: float, won: bool,
                ratio_true: float | None = None) -> None:
        # TWO AVERAGES, because `ratio` was serving two jobs with opposite needs.
        #
        #   b["ratio"]     EMA of the SIGNED clipped ratio. Drift detection wants
        #                  this: `status()` asks whether recent outcomes have
        #                  moved away from the long run, and sign is the signal.
        #   b["abs_ratio"] EMA of the MAGNITUDE. `calibration_gain` wants this,
        #                  and reading the signed average instead was a genuine
        #                  inversion: +3 and -3 cancel, so on the live record the
        #                  signed EMA sat at -0.274 while the median |true ratio|
        #                  was 14.4. `abs(-0.274) = 0.27` told the gain to shrink
        #                  expected_move by 4x when the evidence said grow it by
        #                  ~14x. It was correcting backwards, confidently.
        mag = min(MAG_CLIP, abs(ratio if ratio_true is None else ratio_true))
        keys = [("policies", policy), ("policies", f"{policy}@{regime}"),
                ("drivers", driver or "unattributed")]
        for scope, key in keys:
            b = self._bucket(scope, key)
            b["n"] += 1
            b["wins"] += 1 if won else 0
            a = 1.0 / min(b["n"], 1.0 / 0.15)      # decaying average -> EMA(0.15)
            b["ratio"] = ratio if b["ratio"] is None else (1 - a) * b["ratio"] + a * ratio
            prev_mag = b.get("abs_ratio")
            b["abs_ratio"] = mag if prev_mag is None else (1 - a) * prev_mag + a * mag
            b["score"] = score if b["score"] is None else (1 - a) * b["score"] + a * score
            b["recent"] = (b.get("recent") or [])[-(DRIFT_WINDOW - 1):] + [round(ratio, 3)]

    # -- posteriors (docs/design/LEARNING.md §4) ------------------------------------
    @staticmethod
    def _posterior(b: dict) -> tuple[float, float]:
        """Beta(Jeffreys) mean for P(direction right) and its sample shrink."""
        n, w = b.get("n", 0), b.get("wins", 0)
        p = (w + 0.5) / (n + 1.0) if n else 0.5
        return p, n / (n + N_HALF)

    def _skill(self, policy: str, regime: str | None) -> tuple[float, float, int]:
        """Regime-specific posterior when it has standing, else pooled."""
        pol = (self._s.get("policies") or {})
        if regime:
            rb = pol.get(f"{policy}@{regime}") or {}
            if rb.get("n", 0) >= REGIME_MIN_N:
                p, s = self._posterior(rb)
                return p, s, rb["n"]
        b = pol.get(policy) or {}
        p, s = self._posterior(b)
        return p, s, b.get("n", 0)

    # -- what the books ask for ----------------------------------------------
    def size_multiplier(self, policy: str, regime: str | None = None) -> float:
        """Reward/penalty, governed by uncertainty. Exactly 1.0 when untested."""
        if self.status(policy) == "degraded":
            return SIZE_BOUNDS[0]
        p, shrink, _ = self._skill(policy, regime)
        edge = (p - 0.5) * 2.0
        return max(SIZE_BOUNDS[0], min(SIZE_BOUNDS[1], 1.0 + shrink * edge * EDGE_GAIN))

    def calibration_gain(self, policy: str) -> float:
        """Correct systematic over/under-prediction — shrunk by sample count.

        Reads the MAGNITUDE average, not the signed one. `abs(EMA(signed))`
        cancels wins against losses: on the live record it gave 0.27 — a
        4x SHRINK — while the median |true ratio| was 14.4, i.e. the opposite
        correction to the one the evidence demanded. See `_update`.

        Falls back to the old signed reading only for buckets written before
        `abs_ratio` existed, so an existing state file keeps working rather than
        silently reverting to gain 1.0 and discarding what it had learned.
        """
        b = (self._s.get("policies") or {}).get(policy) or {}
        if not b.get("n"):
            return 1.0
        raw = b.get("abs_ratio")
        if raw is None:
            if b.get("ratio") is None:
                return 1.0
            raw = abs(b["ratio"])
        raw = raw or 1.0
        _, shrink = self._posterior(b)
        blended = 1.0 + shrink * (raw - 1.0)         # toward reality, gradually
        return max(GAIN_BOUNDS[0], min(GAIN_BOUNDS[1], blended))

    # -- self-defence (docs/design/LEARNING.md §7) ----------------------------------
    def status(self, policy: str) -> str:
        b = (self._s.get("policies") or {}).get(policy) or {}
        rec = b.get("recent") or []
        if b.get("n", 0) < DRIFT_WINDOW or len(rec) < DRIFT_WINDOW:
            return "learning"
        mu = sum(rec) / len(rec)
        sd = (sum((x - mu) ** 2 for x in rec) / max(1, len(rec) - 1)) ** 0.5
        long_run = b.get("ratio") or 0.0
        if sd > 1e-9 and abs(mu - long_run) / sd > DRIFT_Z:
            return "degraded"
        p, _ = self._posterior(b)
        return "degraded" if p < 0.35 else "healthy"

    def regime_break(self) -> bool:
        """All policies degrading at once is a changed world, not six bugs."""
        pols = [k for k in (self._s.get("policies") or {}) if "@" not in k]
        graded = [p for p in pols if (self._s["policies"][p].get("n", 0) >= DRIFT_WINDOW)]
        return bool(graded) and all(self.status(p) == "degraded" for p in graded)

    # -- capital allocation, weekly (docs/design/LEARNING.md §6) --------------------
    def risk_budgets(self, policies: list[str]) -> dict:
        """Share of capital per policy: drifts toward demonstrated skill."""
        state = self._s.setdefault("budgets", {})
        last = state.get("_updated")
        due = True
        if last:
            try:
                due = (_now() - datetime.fromisoformat(last)) >= timedelta(days=7)
            except ValueError:
                due = True
        cur = {p: float(state.get(p, 1.0 / max(1, len(policies)))) for p in policies}
        if not due:
            return cur
        weights = {}
        for p in policies:
            sk, shrink, _ = self._skill(p, None)
            w = 1.0 + (sk - 0.5) * 2.0 * shrink
            if self.status(p) == "degraded":
                w = 0.2
            weights[p] = max(0.05, w)
        tot = sum(weights.values()) or 1.0
        # Targets, then rate-limited moves whose deltas are made to CANCEL, so
        # the budget always sums to 1 without a renormalisation that could push
        # a policy back through its own ceiling.
        deltas = {}
        for p in policies:
            target = max(BUDGET_BOUNDS[0], min(BUDGET_BOUNDS[1], weights[p] / tot))
            deltas[p] = max(-BUDGET_STEP, min(BUDGET_STEP, target - cur[p]))
        drift = sum(deltas.values()) / max(1, len(policies))
        out = {}
        for p in policies:
            v = cur[p] + deltas[p] - drift
            out[p] = round(max(BUDGET_BOUNDS[0], min(BUDGET_BOUNDS[1], v)), 4)
        short = round(1.0 - sum(out.values()), 4)
        if abs(short) > 1e-4:      # residual stays UNALLOCATED (a cash buffer),
            out["_unallocated"] = short   # never forced onto a capped policy
        out["_updated"] = _now().isoformat()
        self._s["budgets"] = out
        self._save()
        return {p: v for p, v in out.items() if not p.startswith("_")}

    # -- reporting -----------------------------------------------------------
    def report(self) -> dict:
        pol = self._s.get("policies") or {}
        rows = {}
        for k, b in pol.items():
            p, shrink = self._posterior(b)
            rows[k] = {"n": b.get("n", 0), "skill": round(p, 3),
                       "confidence": round(shrink, 2),
                       "calibration": round(b.get("ratio") or 0.0, 2),
                       "size_x": round(self.size_multiplier(k.split("@")[0],
                                                            k.split("@")[1] if "@" in k else None), 2),
                       "status": self.status(k.split("@")[0])}
        return {"policies": rows, "drivers": self._s.get("drivers", {}),
                "budgets": {k: v for k, v in (self._s.get("budgets") or {}).items()
                            if not k.startswith("_")},
                "open_claims": len(self._s.get("open", {})),
                "regime_break": self.regime_break()}
