"""The learning spine — one coherent learner for an unattended system.

Design and rationale: docs/LEARNING.md. In brief:

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

# --- learning constants (documented in docs/LEARNING.md §4, §6) -------------
N_HALF = 12.0             # sample count at which evidence carries half weight
EDGE_GAIN = 0.8           # how hard proven edge moves size
SIZE_BOUNDS = (0.5, 1.4)  # a bad policy shrinks; a good one cannot run away
GAIN_BOUNDS = (0.25, 3.0)  # expectation-scaling limits
RATIO_CLIP = 3.0          # one freak outcome must not rewrite the model
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
        self._append({"id": tid, "ts": _now().isoformat(), "state": "open",
                      "policy": policy, "symbol": symbol, "direction": int(direction),
                      "signal": round(float(signal), 4), "regime": regime,
                      "vol_daily": round(float(vol_daily), 5),
                      "horizon_days": int(horizon_days), "driver": driver,
                      "notional": round(float(notional), 2),
                      "expected_move": round(exp, 5), "gain_used": round(gain, 3)})
        self._s.setdefault("open", {})[f"{policy}:{symbol}"] = {
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
        ratio = max(-RATIO_CLIP, min(RATIO_CLIP, signed / exp))

        # SCORE (docs/LEARNING.md §3): direction is the only true mistake, and
        # conviction makes being wrong worse. Costs must be cleared to count.
        conviction = max(0.2, min(1.0, float(claim.get("signal", 0.2)) * 5))
        if signed <= -cost_frac:
            score = -min(1.0, 0.5 + 0.5 * conviction)     # confidently wrong hurts more
        elif signed >= max(cost_frac, HIT_FRACTION * exp):
            score = 1.0
        else:
            score = 0.0                                    # right but inside the noise
        won = signed > cost_frac

        out = {"id": claim["id"], "ts": _now().isoformat(), "state": "settled",
               "policy": policy, "symbol": symbol, "regime": claim.get("regime", "neutral"),
               "expected_move": round(exp, 5), "realized_move": round(signed, 5),
               "ratio": round(ratio, 3), "score": round(score, 3), "won": won,
               "held_days": held_days, "exit_reason": exit_reason,
               "driver": claim.get("driver", "")}
        self._append(out)
        self._update(policy, claim.get("driver", ""), claim.get("regime", "neutral"),
                     ratio, score, won)
        self._save()
        return out

    def _bucket(self, scope: str, key: str) -> dict:
        return self._s.setdefault(scope, {}).setdefault(
            key, {"n": 0, "wins": 0, "ratio": None, "score": None, "recent": []})

    def _update(self, policy: str, driver: str, regime: str,
                ratio: float, score: float, won: bool) -> None:
        keys = [("policies", policy), ("policies", f"{policy}@{regime}"),
                ("drivers", driver or "unattributed")]
        for scope, key in keys:
            b = self._bucket(scope, key)
            b["n"] += 1
            b["wins"] += 1 if won else 0
            a = 1.0 / min(b["n"], 1.0 / 0.15)      # decaying average -> EMA(0.15)
            b["ratio"] = ratio if b["ratio"] is None else (1 - a) * b["ratio"] + a * ratio
            b["score"] = score if b["score"] is None else (1 - a) * b["score"] + a * score
            b["recent"] = (b.get("recent") or [])[-(DRIFT_WINDOW - 1):] + [round(ratio, 3)]

    # -- posteriors (docs/LEARNING.md §4) ------------------------------------
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
        """Correct systematic over/under-prediction — shrunk by sample count."""
        b = (self._s.get("policies") or {}).get(policy) or {}
        if not b.get("n") or b.get("ratio") is None:
            return 1.0
        _, shrink = self._posterior(b)
        raw = abs(b["ratio"]) or 1.0
        blended = 1.0 + shrink * (raw - 1.0)         # toward reality, gradually
        return max(GAIN_BOUNDS[0], min(GAIN_BOUNDS[1], blended))

    # -- self-defence (docs/LEARNING.md §7) ----------------------------------
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

    # -- capital allocation, weekly (docs/LEARNING.md §6) --------------------
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
