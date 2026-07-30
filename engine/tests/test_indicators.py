"""Sanity tests for the extended indicator library (pure-python, no market data)."""
import math
import random
from collections import namedtuple

from ai_investing import indicators as ind

Bar = namedtuple("Bar", "ts open high low close volume")


def _bars(closes, vol=1000.0):
    out = []
    for i, c in enumerate(closes):
        out.append(Bar(i, c, c * 1.01, c * 0.99, c, vol))
    return out


UP = [100 + i for i in range(60)]          # steady uptrend
DOWN = [160 - i for i in range(60)]        # steady downtrend
FLAT = [100.0] * 60


def test_macd_sign_follows_trend():
    m_up = ind.macd(UP)
    m_dn = ind.macd(DOWN)
    assert m_up and m_up[0] > 0            # macd line positive in an uptrend
    assert m_dn and m_dn[0] < 0
    assert ind.macd(UP[:20]) is None       # not enough data


def test_bollinger_pct_b():
    up = ind.bollinger(UP)
    assert up and up[3] > 0.5              # trending price rides the upper half
    u, mid, lo, _ = ind.bollinger(FLAT)
    assert math.isclose(mid, 100.0)
    assert math.isclose(u, lo)             # zero-width band on flat prices


def test_stochastic_extremes():
    k_up, _ = ind.stochastic(_bars(UP))
    k_dn, _ = ind.stochastic(_bars(DOWN))
    assert k_up > 80 and k_dn < 20


def test_roc_and_realized_vol():
    assert ind.roc(UP, 20) > 0 > ind.roc(DOWN, 20)
    rv = ind.realized_vol([100 * (1.01 ** i) for i in range(60)], 30)
    assert rv is not None and rv < 0.05    # constant growth = ~zero vol
    random.seed(7)
    noisy = [100]
    for _ in range(59):
        noisy.append(noisy[-1] * (1 + random.uniform(-0.03, 0.03)))
    assert ind.realized_vol(noisy, 30) > rv


def test_obv_and_vwap():
    assert ind.obv(_bars(UP)) > 0 > ind.obv(_bars(DOWN))
    v = ind.vwap(_bars(FLAT))
    assert v is not None and math.isclose(v, 100.0, rel_tol=1e-6)


def test_adx_trend_vs_chop():
    trend = ind.adx(_bars(UP))
    random.seed(3)
    chop_px = [100 + random.uniform(-1, 1) for _ in range(60)]
    chop = ind.adx(_bars(chop_px))
    assert trend is not None and chop is not None
    assert trend > 25 > chop               # strong trend vs noise


def test_donchian_and_drawdown():
    hi, lo, pos = ind.donchian(_bars(UP))
    assert pos > 0.9                       # uptrend close sits at channel top
    assert ind.max_drawdown(UP) == 0.0
    assert math.isclose(ind.max_drawdown([100, 50, 75]), -0.5)
