"""What the market already knows: discount signals the price has already moved on.

News that confirms what the tape already did is not a trade — the surprise is
gone. For each asset with a field impact, compare the impact's direction against
the asset's own recent move measured in vol units (z of the ~5-day return):

  * price already ran the SAME way >= 0.5 sigma  ->  part of the signal is
    priced in; the discount grows with the size of the run, capped at 80%
    (never fully zero: trends do continue);
  * price moved the OTHER way or barely moved    ->  nothing priced in, the
    full signal stands (and a contra-move means MORE room, not less — but we
    don't add on top; asymmetric humility).

Volume weights the verdict when snapshots carry it: a run on a HEAVY tape is
real repricing (information consumed -> bigger discount); the same run on a
thin tape is drift (less was decided -> smaller discount).

Output feeds asset_impacts (`momentum_z`, `priced_in`, `rel_volume`) and the
adviser, which multiplies its field-driven conviction by (1 - priced_in).
"""
from __future__ import annotations

import math

from ai_investing.brain.scale import price_series, relative_volume, volume_series

LOOKBACK = 5          # snapshots ~ trading days
MIN_Z = 0.5           # moves under half a sigma carry no information
FULL_Z = 3.0          # a 3-sigma run in the signal's direction = maximally priced
MAX_DISCOUNT = 0.8
VOL_FACTOR_LO, VOL_FACTOR_HI = 0.7, 1.4   # thin tape softens, heavy tape hardens


def momentum_z(prices: list[float], vol_daily: float) -> float | None:
    """Recent return over up to LOOKBACK snapshots, in sigma units."""
    if len(prices) < 2 or not vol_daily:
        return None
    k = min(LOOKBACK, len(prices) - 1)
    p0, p1 = prices[-1 - k], prices[-1]
    if p0 <= 0:
        return None
    ret = p1 / p0 - 1.0
    return ret / (vol_daily * math.sqrt(k))


def priced_in_scores(settings, asset_impacts: dict[str, dict],
                     vols: dict[str, float]) -> dict[str, dict]:
    """{SYMBOL: {momentum_z, priced_in}} — annotates asset_impacts IN PLACE too."""
    series = price_series(settings)
    volumes = volume_series(settings)
    out: dict[str, dict] = {}
    for sym, row in asset_impacts.items():
        vol = vols.get(sym.upper())
        z = momentum_z(series.get(sym.upper(), []), vol) if vol else None
        if z is None:
            continue
        impact = row.get("impact", 0.0)
        discount = 0.0
        if impact and abs(z) >= MIN_Z and (z > 0) == (impact > 0):
            discount = min(MAX_DISCOUNT,
                           MAX_DISCOUNT * (abs(z) - MIN_Z) / (FULL_Z - MIN_Z))
            rv = relative_volume(volumes.get(sym.upper(), []), k=LOOKBACK)
            if rv is not None:
                # heavy tape = the market really decided; thin tape = drift
                factor = max(VOL_FACTOR_LO, min(VOL_FACTOR_HI, 0.7 + 0.35 * rv))
                discount = min(MAX_DISCOUNT, discount * factor)
                row["rel_volume"] = round(rv, 2)
        row["momentum_z"] = round(z, 2)
        row["priced_in"] = round(discount, 3)
        out[sym.upper()] = {"momentum_z": row["momentum_z"], "priced_in": row["priced_in"]}
    return out
