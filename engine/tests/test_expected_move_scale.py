"""What `expected_move` actually claims, and the two ways it was wrong.

Both were found on 2026-08-22 while deciding whether to raise the saturated
gain ceilings — a decision the user delegated. The answer was **no**, and the
reason is the first half of this file.

--------------------------------------------------------------------------
1. THE 14x IS NOISE, NOT MISCALIBRATION
--------------------------------------------------------------------------
§4.45 measured median |realised/expected| = **14.4** across 19 settled claims
and concluded `expected_move` is "one to two orders of magnitude too small".
That reading makes raising the gain look obviously right. It is obviously
wrong, and the control that shows it is what the ratio would be with NO
signal at all:

    median |realised / expected|              14.4
    median  own-5d-volatility / expected      15.5   <-- pure noise
    directional hit rate                       0.526 (n=19, coin flip)

The two are indistinguishable. `expected_move` is the move ATTRIBUTABLE to the
event; `realized_move` is the asset's TOTAL move over five days, which its own
volatility dominates. Their ratio measures signal-to-noise, not calibration
error, and it cannot be driven to 1.0 by any gain — only by an asset that does
nothing except what the event told it to.

Raising the gain to ~14x would have made every `expected_move` claim the
model predicts the asset's entire five-day range. That figure feeds position
sizing, the sleeve's risk/reward and stop distances. **The gain ceilings stay
where they are, and this file is why.**

--------------------------------------------------------------------------
2. EVERY EQUITY CLAIM WAS SIZED OFF THE SAME 2% CONSTANT
--------------------------------------------------------------------------
Visible in the same table once the open rows were joined: all 17 equity claims
carry `vol_daily = 0.0200` EXACTLY. Only BTC (0.0194) and ETH (0.0409) differ,
because the crypto path computes its own.

`brain/core.py` builds TWO dicts from one graph read — `_shock_assets` (fresh
shock, what the event sleeve trades) and `asset_impacts` (accumulated field).
`enrich_with_scale` ran on the second and not the first, so the sleeve's
`row.get("vol_daily") or 0.02` fell through to the literal on every claim it
has ever opened. JPM (~1.2% daily) and MP (~5%) were sized off one number.

The same shape as §4.14, §4.23, §4.36 and §4.49: one of two paths fixed.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_investing.learning.spine import LearningSpine  # noqa: E402


# --- 1. the ratio is a signal-to-noise measure, not a calibration error ------

def _noise_ratio(vol_daily: float, horizon: int, impact: float, gain: float) -> float:
    """What |realised/expected| comes out at when the asset moves ONLY on its
    own volatility — i.e. when the event explained nothing at all.

    E|X| for a driftless normal over h days is vol*sqrt(h)*sqrt(2/pi).
    """
    expected = abs(impact) * vol_daily * math.sqrt(horizon) * gain
    return (vol_daily * math.sqrt(horizon) * 0.7979) / expected


def test_the_observed_ratio_is_what_pure_noise_produces():
    """The control §4.45 did not have. With the live record's typical impact
    (~0.06) and gain (0.73), a pure-noise asset yields ~18 — bracketing the
    14.4 that was read as the model being 14x too small."""
    r = _noise_ratio(vol_daily=0.02, horizon=5, impact=0.06, gain=0.73)
    assert 10 < r < 30, r
    # and the measured 14.4 sits inside that, so the two are indistinguishable
    assert abs(r - 14.4) < 10, \
        f"noise alone gives {r:.1f}; the measured 14.4 must be within reach of it"


def test_no_gain_can_drive_the_ratio_to_one():
    """The property that makes raising the ceiling futile as well as harmful.

    To reach ratio 1.0 the expectation must equal the asset's whole 5-day
    range, which means claiming the event explains 100% of the move. At the
    live impact of ~0.06 that needs a gain above 13 — and the model would then
    be asserting something it has no evidence for and a 52.6% hit rate against.
    """
    needed = _noise_ratio(0.02, 5, 0.06, 1.0)
    assert needed > 10, needed
    for gain in (2.0, 3.0):
        assert _noise_ratio(0.02, 5, 0.06, gain) > 4, (
            "a gain inside the current bounds should NOT close the gap — if it "
            "does, the gap was calibration after all and this file is wrong")


def test_a_bigger_impact_shrinks_the_ratio_without_touching_gain():
    """The honest lever. The ratio falls when the event explains MORE of the
    move — a graph-wiring question — not when the gain is turned up."""
    weak = _noise_ratio(0.02, 5, impact=0.02, gain=1.0)
    strong = _noise_ratio(0.02, 5, impact=0.50, gain=1.0)
    assert strong < weak / 10, (weak, strong)
    assert strong < 2.0, "an event explaining half the move should nearly close it"


def test_the_scale_law_is_still_dimensionally_sound():
    """Guard on the formula itself, so 'the ratio is noise' is not used to
    excuse a real units defect later. Doubling any input doubles the output."""
    base = LearningSpine.expected_move(0.1, 0.02, 5, 1.0)
    assert LearningSpine.expected_move(0.2, 0.02, 5, 1.0) == 2 * base
    assert LearningSpine.expected_move(0.1, 0.04, 5, 1.0) == 2 * base
    assert LearningSpine.expected_move(0.1, 0.02, 5, 2.0) == 2 * base
    assert abs(LearningSpine.expected_move(0.1, 0.02, 20, 1.0) - 2 * base) < 1e-12


# --- 2. the fresh-shock dict must carry a real vol --------------------------

def test_the_fresh_shock_dict_is_enriched_like_the_field_dict():
    """`_shock_assets` and `asset_impacts` come from one graph read. Enriching
    one and not the other is how every equity claim got vol_daily=0.02."""
    import ast
    src = Path(__file__).resolve().parents[1] / "ai_investing" / "brain" / "core.py"
    tree = ast.parse(src.read_text())
    enriched = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "enrich_with_scale" and node.args):
            enriched.add(ast.unparse(node.args[0]))
    assert "asset_impacts" in enriched, enriched
    assert "self._shock_assets" in enriched, (
        "the event sleeve trades `_shock_assets`; unenriched it has no "
        f"vol_daily, so every claim falls back to a 2% literal. enriched: {enriched}")


def test_the_sleeves_fallback_is_reachable_only_as_a_fallback():
    """The 0.02 literal stays — a missing vol must not take a cycle down — but
    it must be a genuine last resort, not the value every claim receives. This
    pins the literal's presence so that if it is ever deleted, the deleter has
    to think about what an absent vol should do."""
    src = (Path(__file__).resolve().parents[1] / "ai_investing" / "strategy"
           / "event_sleeve.py").read_text()
    assert 'row.get("vol_daily") or 0.02' in src, \
        "the fallback changed shape — re-check what an absent vol now does"


def test_the_audit_cannot_report_the_ratio_without_its_control():
    """Found by mutation: blanking `median_noise_ratio` in `brain_audit.py`
    broke nothing, so the audit could go back to printing 14.4 on its own —
    which is exactly the reading that makes raising the gain look right.

    A number that is only safe when read beside another must not be printable
    without it. Same class as §4.48: a guard that passes while the result it
    guards is wrong.
    """
    import ast
    src = (Path(__file__).resolve().parents[2] / "scripts" / "brain_audit.py").read_text()
    tree = ast.parse(src)
    keys = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "median_observed_ratio":
                    keys = {ast.unparse(kk): ast.unparse(vv)
                            for kk, vv in zip(node.keys, node.values)
                            if isinstance(kk, ast.Constant)}
    assert keys, "brain_audit.py no longer reports median_observed_ratio at all"
    noise = keys.get("'median_noise_ratio'")
    assert noise and noise != "None", (
        "the observed ratio is reported without its noise control. 14.4 alone "
        "reads as 'the model is 14x too small'; beside 15.5 it reads as noise.")
    assert "'hit_rate'" in keys, \
        "the ratio must be printed beside the directional hit rate too"
    assert "'ratio_is_indistinguishable_from_noise'" in keys, \
        "the audit must state the conclusion, not leave it to be re-derived"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} expected-move scale tests passed.")
