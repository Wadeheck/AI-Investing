"""A hit rate is not evidence until it is stated in independent observations.

§4.53. `brain_audit.py --section reach` reported raw symbol-days as `n` and a
hit rate beside it, and that table was used on 2026-08-22 to argue for a first
live order on an unproven market path (`O39.SI`, 7 days, hit 0.86).

The rows are daily readings of a 5-day forward return, so consecutive rows
overlap almost entirely. Corrected:

    market  raw n  hit    n_ind   p       significant
    KS          9  0.889      2   0.250   False
    SI          8  0.875      2   0.250   False
    HK         16  0.562      3   0.500   False
    US         51  0.529     10   0.623   False

**Not one row is distinguishable from a coin flip**, and every entry in
`correct_but_never_held` has n_independent = 1. The "brain is best where it
cannot trade" finding — a headline of BRAIN_REVIEW_2026-08-21 §5.1 — was noise,
ranked.

This is the SAME defect as §4.37 (the scorecard counting one view 65 times) and
§4.47 (the calibrator about to grade on ~4 observations), in the third module.
Both of those were fixed where they were found. This one — the section actually
used to decide which market to trade — was the seam between them.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import brain_audit  # noqa: E402


def _binom_p(k, n):
    return sum(math.comb(n, i) for i in range(k, n + 1)) / (2 ** n)


def test_seven_symbol_days_is_not_seven_observations():
    """O39.SI as it actually stood: 6 of 7 symbol-days on a 5-day horizon.

    Read raw it looks like p=0.06 and nearly interesting. Read in the unit that
    exists it is one observation, and one observation of a coin is a coin.
    """
    assert _binom_p(6, 7) < 0.10, "raw 6/7 does look suggestive — that is the trap"
    n_eff = max(1, round(7 / 5))
    assert n_eff == 1
    assert _binom_p(1, 1) == 0.5, "one independent observation carries no evidence"


def test_a_hit_rate_needs_forty_symbol_days_to_mean_anything():
    """The bar, stated in the unit a reader will actually have. At a 0.86 hit
    rate it takes 8 independent observations to clear p<0.05 — which is 40
    consecutive symbol-days, not 7."""
    need = next(n for n in range(2, 40) if _binom_p(round(0.86 * n), n) < 0.05)
    assert need == 8, need
    assert need * 5 == 40


def test_the_reach_report_states_what_its_sample_is_worth():
    """The fix, pinned at the point of publication rather than of reading —
    §4.37's lesson. A `hit` may not be published without the two fields that
    say what it is worth."""
    import ast
    src = (Path(__file__).resolve().parents[2] / "scripts" / "brain_audit.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "reach")
    # `ast.unparse` normalises string quotes to single, so match the bare name.
    body = ast.unparse(fn)
    for field in ("n_independent", "p_value", "significant"):
        assert field in body, f"reach() publishes a hit rate without {field}"
    # Not merely "the word horizon appears" — mutation showed that passes with
    # the division removed, because `horizon` is also the parameter name and is
    # mentioned in the note. Assert the DIVISION itself.
    divides = [n for n in ast.walk(fn)
               if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div)
               and isinstance(n.right, ast.Name) and n.right.id == "horizon"]
    # TWO of them, and the count is the point: reach() reports at two levels —
    # `by_market` and `correct_but_never_held` — and each derives its own
    # independent count. Asserting "at least one" let a mutation remove the
    # market-level division while the symbol-level one kept the test green,
    # which is precisely the one-of-N-paths shape this file is about.
    assert len(divides) >= 2, (
        f"only {len(divides)} `/ horizon` in reach(); both by_market and "
        "correct_but_never_held must derive an independent count, or one of "
        "them is reporting raw symbol-days as evidence")


def test_the_significance_verdict_is_computed_not_asserted():
    """A hardcoded `significant: False` would pass the test above while
    telling the reader nothing. It must come from the arithmetic."""
    import ast
    src = (Path(__file__).resolve().parents[2] / "scripts" / "brain_audit.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "reach")
    for node in ast.walk(fn):
        if (isinstance(node, ast.Dict)):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "significant":
                    assert not isinstance(v, ast.Constant), \
                        "significant is a literal, not a measurement"


def test_binomial_not_t_test():
    """§4.37 again: `hit` is Bernoulli. A t-test degenerates on a perfect run
    (DEO went 11/11 and was silently dropped). The reach section must use the
    exact binomial like the rest of the audit does."""
    src = (Path(__file__).resolve().parents[2] / "scripts" / "brain_audit.py").read_text()
    i = src.index("def reach(")
    window = src[i:i + 4000]
    assert "comb(" in window, "reach() does not use an exact binomial"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} reach-significance tests passed.")
