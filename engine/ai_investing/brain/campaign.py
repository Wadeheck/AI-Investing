"""Campaign detector: a per-node manipulation-pressure index + pump lifecycle.

Pumps have a fingerprint that no single headline shows:

  * burst      — mention velocity accelerating (stories/12h vs the 4-day base);
                 organic news decays, campaigns crescendo
  * chorus     — many DISTINCT low-trust sources singing at once; real news
                 breaks on wires first, campaigns break on blogs simultaneously
  * coordination — >=3 distinct low-trust sources inside one 3h window;
                 syndication timing is the campaign's signature
  * noise pressure — manipulation-flagged event mass touching the node

    pressure = 0.35·burst + 0.30·chorus + 0.15·coordination + 0.20·noise

For PUMPED ASSETS the detector also stages the lifecycle from price snapshots,
because your own event study says fading a pump has a timing problem:

    building    pressure high, price hasn't moved yet   -> do not chase, watch
    hype_burst  price running WITH the campaign         -> never fade (rule 1
                of shorting pumps: not while it's working), never buy
    dump        the run has cracked (last moves down    -> fade window opens
                after a real run-up)

Persisted to data/campaigns.json; the adviser haircuts longs by pressure and
the contrarian composer only fades in the dump phase.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta, timezone

from ai_investing.brain.events import source_trust
from ai_investing.brain.scale import (price_series, prior_vol, realized_daily_vol,
                                      relative_volume, volume_series)

W_BURST, W_CHORUS, W_COORD, W_NOISE = 0.35, 0.30, 0.15, 0.20
LOW_TRUST = 0.5     # inclusive: unknown sources (default trust 0.5) ARE the pump vector
WINDOW_HOURS = 96.0            # lookback for the baseline
RECENT_HOURS = 12.0            # the "now" bucket for burst velocity
MIN_PRESSURE = 0.25            # below this a node isn't worth reporting
RUNUP_SIGMAS = 2.0             # a "real run-up" = >= 2 sigma over ~5 snapshots


def _path(settings) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(settings.brain.db_path)),
                        "campaigns.json")


def _parse_ts(ts: str) -> datetime | None:
    try:
        d = datetime.fromisoformat(ts)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def pressure_index(events: list[dict], now: datetime | None = None,
                   settings=None) -> dict[str, dict]:
    """{node: {pressure, burst, chorus, coordination, noise}} from recent events
    (pass signal AND noise events — noise is the point here). With `settings`
    the low-trust judgment uses LEARNED trust, so a feed that earned precision
    stops counting toward the chorus."""
    now = now or datetime.now(timezone.utc)
    per_node: dict[str, list[tuple[datetime, str, float, bool, float]]] = {}
    for ev in events or []:
        t = _parse_ts(ev.get("ts", ""))
        if t is None or (now - t) > timedelta(hours=WINDOW_HOURS):
            continue
        trust = source_trust(ev.get("source", ""), settings)
        for nid in ev.get("nodes", []):
            per_node.setdefault(nid, []).append(
                (t, ev.get("source", ""), trust, bool(ev.get("is_noise")),
                 float(ev.get("magnitude", 0.0) or 0.0)))
    out: dict[str, dict] = {}
    for nid, rows in per_node.items():
        recent = [r for r in rows if (now - r[0]) <= timedelta(hours=RECENT_HOURS)]
        base_n = len(rows) - len(recent)
        base_rate = base_n / ((WINDOW_HOURS - RECENT_HOURS) / RECENT_HOURS)  # per 12h
        burst = 0.0
        if len(recent) >= 2:
            burst = min(1.0, (len(recent) - base_rate) / 4.0) if len(recent) > base_rate else 0.0
        low = [r for r in recent if r[2] <= LOW_TRUST]
        chorus = min(1.0, len({r[1] for r in low}) / 4.0)
        coord = 0.0
        lows_sorted = sorted(low, key=lambda r: r[0])
        for i in range(len(lows_sorted)):
            srcs = {lows_sorted[j][1] for j in range(i, len(lows_sorted))
                    if lows_sorted[j][0] - lows_sorted[i][0] <= timedelta(hours=3)}
            if len(srcs) >= 3:
                coord = 1.0
                break
        noise = min(1.0, sum(r[4] for r in rows if r[3]) * 0.5)
        pressure = round(min(1.0, W_BURST * burst + W_CHORUS * chorus
                             + W_COORD * coord + W_NOISE * noise), 3)
        if pressure >= MIN_PRESSURE:
            out[nid] = {"pressure": pressure, "burst": round(burst, 3),
                        "chorus": round(chorus, 3), "coordination": coord,
                        "noise": round(noise, 3), "stories_12h": len(recent)}
    return out


def _phase(prices: list[float], vol: float) -> str | None:
    """Stage the pump from the last ~6 snapshots: building / hype_burst / dump."""
    if len(prices) < 3:
        return None
    k = min(5, len(prices) - 1)
    runup = prices[-1] / prices[-1 - k] - 1.0
    last = prices[-1] / prices[-2] - 1.0
    sigma5 = vol * math.sqrt(k)
    peak = max(prices[-1 - k:])
    off_peak = prices[-1] / peak - 1.0 if peak > 0 else 0.0
    if runup >= RUNUP_SIGMAS * sigma5 and last >= 0:
        return "hype_burst"
    if (off_peak <= -1.5 * vol and max(prices[-1 - k:-1]) / prices[-1 - k] - 1.0
            >= RUNUP_SIGMAS * sigma5):
        return "dump"                     # ran hard, now cracked below the peak
    if abs(runup) < sigma5:
        return "building"                 # the noise arrived before the move
    return None


def update(settings, store, graph, now: datetime | None = None) -> dict[str, dict]:
    """Compute pressure from the store's recent events (noise included), stage
    pumped assets, persist, and return the report."""
    now = now or datetime.now(timezone.utc)
    try:
        events = store.recent_events(hours=WINDOW_HOURS, signal_only=False)
    except Exception:
        events = []
    report = pressure_index(events, now, settings)
    series = price_series(settings)
    volumes = volume_series(settings)
    for nid, row in report.items():
        n = graph.nodes.get(nid)
        if n is None or n.type != "asset" or not n.symbol:
            continue
        sym = n.symbol.upper()
        prices = series.get(sym, [])
        vol = realized_daily_vol(prices) or prior_vol(n)
        phase = _phase(prices, vol)
        row["symbol"] = sym
        # volume confirmation: a story burst riding a >=2x tape is the genuine
        # pump signature (retail is actually taking the bait) — pressure rises
        rv = relative_volume(volumes.get(sym, []))
        if rv is not None and rv >= 2.0:
            row["volume_confirmed"] = True
            row["pressure"] = round(min(1.0, row["pressure"] + 0.1), 3)
        if phase:
            row["phase"] = phase
            row["fade_ok"] = phase == "dump"   # never fade a pump that's working
    try:
        os.makedirs(os.path.dirname(_path(settings)), exist_ok=True)
        with open(_path(settings), "w") as fh:
            json.dump({"ts": now.isoformat(), "nodes": report}, fh, indent=1)
    except OSError:
        pass
    return report


def load(settings) -> dict[str, dict]:
    try:
        with open(_path(settings)) as fh:
            return json.load(fh).get("nodes", {})
    except (OSError, json.JSONDecodeError):
        return {}
