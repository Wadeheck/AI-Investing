"""Pure-Python technical indicators (no numpy/pandas required)."""
from __future__ import annotations

from typing import Optional, Sequence


def sma(values: Sequence[float], period: int) -> Optional[float]:
    if period <= 0 or len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema(values: Sequence[float], period: int) -> Optional[float]:
    if period <= 0 or len(values) < period:
        return None
    k = 2 / (period + 1)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


def rsi(values: Sequence[float], period: int = 14) -> Optional[float]:
    if len(values) < period + 1:
        return None
    gains = losses = 0.0
    for i in range(-period, 0):
        change = values[i] - values[i - 1]
        if change >= 0:
            gains += change
        else:
            losses -= change
    avg_gain, avg_loss = gains / period, losses / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def pct_returns(values: Sequence[float]) -> list[float]:
    out: list[float] = []
    for i in range(1, len(values)):
        prev = values[i - 1]
        out.append((values[i] - prev) / prev if prev else 0.0)
    return out


def stdev(values: Sequence[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    return (sum((v - mean) ** 2 for v in values) / (n - 1)) ** 0.5


def zscore(value: float, window: Sequence[float]) -> float:
    sd = stdev(window)
    if sd == 0:
        return 0.0
    return (value - sum(window) / len(window)) / sd


def atr(bars, period: int = 14) -> Optional[float]:
    """Average True Range over OHLC bars (duck-typed: needs .high/.low/.close)."""
    if len(bars) < period + 1:
        return None
    trs = []
    for i in range(1, len(bars)):
        h, low, prev_close = bars[i].high, bars[i].low, bars[i - 1].close
        trs.append(max(h - low, abs(h - prev_close), abs(low - prev_close)))
    if len(trs) < period:
        return None
    return sum(trs[-period:]) / period


def macd(values: Sequence[float], fast: int = 12, slow: int = 26,
         signal: int = 9) -> Optional[tuple[float, float, float]]:
    """(macd_line, signal_line, histogram). Needs slow+signal bars."""
    if len(values) < slow + signal:
        return None
    k_f, k_s = 2 / (fast + 1), 2 / (slow + 1)
    ef = sum(values[:fast]) / fast
    es = sum(values[:slow]) / slow
    line: list[float] = []
    for i, v in enumerate(values):
        if i >= fast:
            ef = v * k_f + ef * (1 - k_f)
        if i >= slow:
            es = v * k_s + es * (1 - k_s)
            line.append(ef - es)
    if len(line) < signal:
        return None
    k_sig = 2 / (signal + 1)
    sig = sum(line[:signal]) / signal
    for v in line[signal:]:
        sig = v * k_sig + sig * (1 - k_sig)
    m = line[-1]
    return m, sig, m - sig


def bollinger(values: Sequence[float], period: int = 20,
              n_std: float = 2.0) -> Optional[tuple[float, float, float, float]]:
    """(upper, middle, lower, %b). %b: 0 = at lower band, 1 = at upper."""
    if len(values) < period:
        return None
    window = values[-period:]
    mid = sum(window) / period
    sd = stdev(window)
    up, lo = mid + n_std * sd, mid - n_std * sd
    pct_b = (values[-1] - lo) / (up - lo) if up != lo else 0.5
    return up, mid, lo, pct_b


def stochastic(bars, period: int = 14, smooth: int = 3) -> Optional[tuple[float, float]]:
    """(%K smoothed, %D). Duck-typed bars: needs .high/.low/.close."""
    if len(bars) < period + smooth:
        return None
    ks = []
    for i in range(-smooth, 0):
        window = bars[len(bars) + i - period + 1: len(bars) + i + 1]
        hi = max(b.high for b in window)
        lo = min(b.low for b in window)
        c = window[-1].close
        ks.append(100 * (c - lo) / (hi - lo) if hi != lo else 50.0)
    k = sum(ks) / smooth
    return k, sum(ks[-min(smooth, len(ks)):]) / min(smooth, len(ks))


def roc(values: Sequence[float], period: int = 20) -> Optional[float]:
    """Rate of change (momentum) over `period` bars, as a fraction."""
    if len(values) < period + 1 or not values[-period - 1]:
        return None
    return values[-1] / values[-period - 1] - 1.0


def obv(bars) -> Optional[float]:
    """On-balance volume: cumulative volume signed by close direction."""
    if len(bars) < 2:
        return None
    total = 0.0
    for i in range(1, len(bars)):
        if bars[i].close > bars[i - 1].close:
            total += bars[i].volume
        elif bars[i].close < bars[i - 1].close:
            total -= bars[i].volume
    return total


def vwap(bars, period: int = 20) -> Optional[float]:
    """Volume-weighted average price of the last `period` bars (typical price)."""
    window = bars[-period:]
    if len(window) < period:
        return None
    vol = sum(b.volume for b in window)
    if vol <= 0:
        return None
    return sum((b.high + b.low + b.close) / 3 * b.volume for b in window) / vol


def adx(bars, period: int = 14) -> Optional[float]:
    """Average Directional Index — trend STRENGTH regardless of direction
    (>25 = trending, <20 = chop). Wilder smoothing."""
    if len(bars) < 2 * period + 1:
        return None
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, len(bars)):
        up = bars[i].high - bars[i - 1].high
        dn = bars[i - 1].low - bars[i].low
        plus_dm.append(up if up > dn and up > 0 else 0.0)
        minus_dm.append(dn if dn > up and dn > 0 else 0.0)
        trs.append(max(bars[i].high - bars[i].low,
                       abs(bars[i].high - bars[i - 1].close),
                       abs(bars[i].low - bars[i - 1].close)))
    a_tr = sum(trs[:period])
    a_p, a_m = sum(plus_dm[:period]), sum(minus_dm[:period])
    dxs = []
    for i in range(period, len(trs)):
        a_tr = a_tr - a_tr / period + trs[i]
        a_p = a_p - a_p / period + plus_dm[i]
        a_m = a_m - a_m / period + minus_dm[i]
        if a_tr <= 0:
            continue
        di_p, di_m = 100 * a_p / a_tr, 100 * a_m / a_tr
        if di_p + di_m > 0:
            dxs.append(100 * abs(di_p - di_m) / (di_p + di_m))
    if len(dxs) < period:
        return None
    a = sum(dxs[:period]) / period
    for d in dxs[period:]:
        a = (a * (period - 1) + d) / period
    return a


def donchian(bars, period: int = 20) -> Optional[tuple[float, float, float]]:
    """(highest high, lowest low, position 0..1 of last close in the channel)."""
    window = bars[-period:]
    if len(window) < period:
        return None
    hi = max(b.high for b in window)
    lo = min(b.low for b in window)
    pos = (window[-1].close - lo) / (hi - lo) if hi != lo else 0.5
    return hi, lo, pos


def realized_vol(values: Sequence[float], period: int = 30,
                 periods_per_year: int = 252) -> Optional[float]:
    """Annualized close-to-close volatility over the last `period` returns."""
    rets = pct_returns(values)
    if len(rets) < period:
        return None
    return stdev(rets[-period:]) * periods_per_year ** 0.5


def max_drawdown(values: Sequence[float]) -> float:
    """Worst peak-to-trough decline as a NEGATIVE fraction (0.0 = never down)."""
    peak, worst = float("-inf"), 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, v / peak - 1.0)
    return worst


def smoothness_anomaly(returns: Sequence[float], periods_per_year: int = 252) -> float:
    """Madoff/Ponzi detector: 0..1 score for returns that are TOO smooth to be
    honest. Real risk assets earn their returns with volatility; a series with
    high steady gains, tiny vol, few down periods, and sticky autocorrelation
    is the statistical fingerprint of smoothed/managed/fabricated returns
    (Madoff's 1%/month, Bitconnect, Terra's Anchor 20%, 'stable' yield tokens).

    Components (each 0..1, averaged):
      - implausible Sharpe   (annualized mean/vol > 3 starts scoring, > 6 maxes)
      - too-few down periods (< 20% negative starts scoring)
      - return autocorrelation (lag-1 > 0.3 starts scoring — real returns don't repeat)
    Returns 0.0 when there's nothing suspicious or not enough data (<30 obs),
    and only ever scores POSITIVE-drift series (steady losses aren't a Ponzi).
    """
    r = [x for x in returns if x is not None]
    n = len(r)
    if n < 30:
        return 0.0
    mean = sum(r) / n
    if mean <= 0:
        return 0.0
    sd = stdev(r)
    if sd == 0:
        return 1.0                      # perfectly constant positive returns: maximal alarm
    sharpe = mean / sd * periods_per_year ** 0.5
    s_sharpe = max(0.0, min(1.0, (sharpe - 3.0) / 3.0))
    down_frac = sum(1 for x in r if x < 0) / n
    s_down = max(0.0, min(1.0, (0.20 - down_frac) / 0.20))
    ac = correlation(r[:-1], r[1:])
    s_ac = max(0.0, min(1.0, (ac - 0.3) / 0.4))
    return round((s_sharpe + s_down + s_ac) / 3.0, 3)


def correlation(a: Sequence[float], b: Sequence[float]) -> float:
    n = min(len(a), len(b))
    if n < 3:
        return 0.0
    a, b = a[-n:], b[-n:]
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return 0.0
    return cov / (va ** 0.5 * vb ** 0.5)
