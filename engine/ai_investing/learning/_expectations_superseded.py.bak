"""The expectation ledger — the brain's contract with itself.

Every entry the books make carries an implicit claim: *this signal, on this
asset, should move it about this much, within about this long*. Until now
nothing wrote that claim down, so nothing could check it. A system that never
compares what it EXPECTED to what HAPPENED cannot improve — it can only
accumulate.

    at entry   record(policy, symbol, expected_move, horizon, driver, ...)
    at exit    settle(trade_id, realized_move)  ->  two learning signals

TWO SIGNALS, deliberately separated — the distinction between a good process
and a good outcome:

  1. CALIBRATION (is the prediction honest?)
     ratio = realized / expected, EMA'd per policy and per driver.
     If a policy keeps predicting +3% and delivering +1%, its future
     expectations are scaled by 0.33 — not punished, CORRECTED. This is the
     same idea as the edge calibrator's global `gain`, applied per policy.

  2. TRUST (does the edge exist at all?)  -> the reward / penalty
     per trade:  +1 right direction AND at least half the expected size
                  0 right direction but undersized (a weak hit)
                 -1 wrong direction (the real mistake)
     EMA'd, then mapped to a SIZE MULTIPLIER in [0.5, 1.4]. A policy that
     keeps being wrong trades smaller until it earns its size back; one that
     keeps being right is allowed more — capped, so a hot streak cannot
     lever the book up.

Both are EMAs with a slow half-life and hard bounds, because the failure mode
of adaptive sizing is over-reacting to noise: three lucky trades must not
double the risk. And both need a minimum sample (MIN_N) before they move
anything at all — until then the multiplier is exactly 1.0 and the system
trades its untuned prior, honestly.

Nothing here ever deletes: data/expectations.jsonl is the permanent record of
every claim the brain made and how it turned out.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone

ALPHA = 0.15          # EMA weight per settled trade (~ half-life of 4-5 trades)
MIN_N = 8             # trades before learning is allowed to change anything
GAIN_BOUNDS = (0.25, 3.0)
TRUST_BOUNDS = (0.5, 1.4)
HIT_FRACTION = 0.5    # realized must reach this share of expected to count as a hit


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ExpectationLedger:
    def __init__(self, settings):
        d = os.path.dirname(os.path.abspath(settings.state_path))
        self.ledger = os.path.join(d, "expectations.jsonl")
        self.path = os.path.join(d, "expectation_state.json")
        self._s = self._load()

    def _load(self) -> dict:
        try:
            with open(self.path) as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            return {"policies": {}, "drivers": {}}

    def _save(self) -> None:
        try:
            with open(self.path, "w") as fh:
                json.dump(self._s, fh, indent=1)
        except OSError:
            pass

    def _append(self, row: dict) -> None:
        try:
            with open(self.ledger, "a") as fh:
                fh.write(json.dumps(row) + "\n")
        except OSError:
            pass

    # -- expectations ---------------------------------------------------------
    @staticmethod
    def expected_move(signal: float, vol_daily: float, horizon_days: int,
                      gain: float = 1.0) -> float:
        """The engine's own scale formula: impact x vol x sqrt(h) x gain."""
        return abs(signal) * max(1e-6, vol_daily) * math.sqrt(max(1, horizon_days)) * gain

    def record(self, policy: str, symbol: str, direction: int, signal: float,
               vol_daily: float, horizon_days: int, driver: str = "",
               notional: float = 0.0) -> str:
        """Write the claim BEFORE the outcome is knowable. Returns a trade id."""
        gain = self.calibration_gain(policy)
        exp = self.expected_move(signal, vol_daily, horizon_days, gain)
        tid = f"{policy}:{symbol}:{_now()}"
        self._append({"id": tid, "ts": _now(), "state": "open", "policy": policy,
                      "symbol": symbol, "direction": int(direction),
                      "signal": round(float(signal), 4),
                      "vol_daily": round(float(vol_daily), 5),
                      "horizon_days": int(horizon_days), "driver": driver,
                      "notional": round(float(notional), 2),
                      "expected_move": round(exp, 5), "gain_used": round(gain, 3)})
        open_ = self._s.setdefault("open", {})
        open_[f"{policy}:{symbol}"] = {"id": tid, "expected_move": exp,
                                       "direction": int(direction), "driver": driver}
        self._save()
        return tid

    # -- outcomes -------------------------------------------------------------
    def settle(self, policy: str, symbol: str, realized_move: float,
               held_days: int = 0, exit_reason: str = "") -> dict | None:
        """Compare the claim with reality and update both learning signals."""
        key = f"{policy}:{symbol}"
        claim = (self._s.get("open") or {}).pop(key, None)
        if not claim:
            return None
        exp = max(1e-6, float(claim["expected_move"]))
        signed = realized_move * (1 if claim["direction"] > 0 else -1)
        ratio = signed / exp
        if signed <= 0:
            score = -1.0                       # wrong direction — the real mistake
        elif signed >= HIT_FRACTION * exp:
            score = 1.0                        # right, and big enough to matter
        else:
            score = 0.0                        # right but undersized
        out = {"id": claim["id"], "ts": _now(), "state": "settled", "policy": policy,
               "symbol": symbol, "expected_move": round(exp, 5),
               "realized_move": round(signed, 5), "ratio": round(ratio, 3),
               "score": score, "held_days": held_days, "exit_reason": exit_reason,
               "driver": claim.get("driver", "")}
        self._append(out)
        self._update(policy, claim.get("driver", ""), ratio, score)
        self._save()
        return out

    @staticmethod
    def _ema(bucket: dict, field: str, value: float) -> None:
        cur = bucket.get(field)
        bucket[field] = value if cur is None else (1 - ALPHA) * cur + ALPHA * value

    def _update(self, policy: str, driver: str, ratio: float, score: float) -> None:
        # clip the ratio before it enters the average: one 20x outlier must not
        # rewrite the calibration
        r = max(-3.0, min(3.0, ratio))
        for scope, key in (("policies", policy), ("drivers", driver or "unattributed")):
            b = self._s.setdefault(scope, {}).setdefault(key, {})
            self._ema(b, "ratio", r)
            self._ema(b, "score", score)
            b["n"] = b.get("n", 0) + 1         # ONE settled trade = one sample

    # -- what the books ask for ----------------------------------------------
    def calibration_gain(self, policy: str) -> float:
        """Scale future expectations by how honest past ones proved."""
        b = (self._s.get("policies") or {}).get(policy) or {}
        if b.get("n", 0) < MIN_N or b.get("ratio") is None:
            return 1.0
        return max(GAIN_BOUNDS[0], min(GAIN_BOUNDS[1], abs(b["ratio"]) or 1.0))

    def size_multiplier(self, policy: str) -> float:
        """The reward / penalty: shrink a policy that keeps being wrong."""
        b = (self._s.get("policies") or {}).get(policy) or {}
        if b.get("n", 0) < MIN_N or b.get("score") is None:
            return 1.0
        # score in [-1, 1] -> multiplier in TRUST_BOUNDS, 0 -> ~0.95
        s = max(-1.0, min(1.0, b["score"]))
        lo, hi = TRUST_BOUNDS
        mid = (lo + hi) / 2
        return max(lo, min(hi, mid + s * (hi - lo) / 2))

    def report(self) -> dict:
        return {"policies": self._s.get("policies", {}),
                "drivers": self._s.get("drivers", {}),
                "open_claims": len(self._s.get("open", {}))}
