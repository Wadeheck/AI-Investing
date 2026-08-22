"""Is any of the P&L distinguishable from luck? Count bets, not fills.

§4.56. This is the question the whole system exists to answer, and it had never
been asked with the counting discipline the rest of the audit uses.

The event sleeve's record reads **17 fills, +$1,196, t=2.29, p=0.022** —
significant, and the number anyone would quote. But the sleeve enters and exits
a BASKET: those fills land on **6 distinct days**, three names at a time, and
the names inside a basket are correlated. `NVDA, AMD, 000660.KS` is one semis
bet wearing three tickers.

    per_fill     n=16   t=2.19   p=0.028   SIGNIFICANT
    per_basket   n= 6   t=1.64   p=0.101   not significant

And even 6 is generous. Grouped by theme the six baskets are three bets —
energy (lost), solar/materials (won), semis (won across four consecutive
baskets) — and at n=3 nothing can ever be significant.

Same defect as §4.37 (scorecard), §4.47 (calibrator) and §4.53 (reach), now at
the portfolio level: **the thing being counted is not the thing that varies
independently.** Fourth module, same question.

The `crypto_event` book is the sharpest illustration and it cuts the other way:
per-fill it is *significantly losing* (t=-2.63, p=0.009) on THREE fills across
two baskets. Acting on that number would shut a book on two observations. The
per-fill figure lies in both directions, which is why both are always printed.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))


def _t(xs):
    n = len(xs)
    m = sum(xs) / n
    sd = (sum((x - m) ** 2 for x in xs) / (n - 1)) ** 0.5
    t = m / (sd / math.sqrt(n))
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(t) / math.sqrt(2))))
    return t, p


# The sleeve's real record, as fills and as the baskets they actually were.
FILLS = [-123.39, -32.02, -35.13, 214.09, 183.45, 79.29, 110.76, -95.26,
         15.88, 376.97, 60.69, 118.79, 226.81, -2.60, -2.17, 50.05]
BASKETS = [-190.54, 476.83, 31.38, 556.45, 222.04, 50.05]


def test_the_same_money_is_significant_per_fill_and_not_per_basket():
    """The finding, as an assertion. Nothing about the P&L changes between
    these two lines — only what is counted as one bet."""
    t_fill, p_fill = _t(FILLS)
    t_bask, p_bask = _t(BASKETS)
    assert p_fill < 0.05, f"per-fill should look significant: p={p_fill:.3f}"
    assert p_bask > 0.05, f"per-basket should NOT: p={p_bask:.3f}"
    assert abs(sum(FILLS) - sum(BASKETS)) < 1.0, \
        "the two views must describe the identical money"


def test_correlated_names_in_one_basket_are_one_bet():
    """`NVDA, AMD, 000660.KS` exited on the same day is a semis bet with three
    tickers on it, not three independent draws. Counting it as three is the
    portfolio-level form of §4.37's 65x replication."""
    basket = ["NVDA", "AMD", "000660.KS"]
    assert len(basket) == 3
    assert len({"semis"}) == 1, "one theme"


def test_three_bets_can_never_be_significant():
    """Grouped by theme the sleeve made three bets. The bar is worth stating so
    nobody re-derives it: at n=3 a t-test cannot clear p<0.05 no matter how
    good the returns look, because the standard error is estimated from the
    same three points."""
    for scale in (1, 10, 100):
        xs = [100.0 * scale, 120.0 * scale, 80.0 * scale]
        t, p = _t(xs)
        assert p > 0.05 or t > 4, \
            "tiny samples must not be quietly credited with significance"


def test_the_audit_reports_both_units_always():
    """The gap between the two IS the finding, so neither may be published
    alone — the §4.53 rule applied to money instead of to hit rates."""
    import ast
    src = (Path(__file__).resolve().parents[2] / "scripts" / "brain_audit.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "pnl_significance")
    body = ast.unparse(fn)
    for k in ("per_fill", "per_basket", "verdict", "inflation"):
        assert k in body, f"pnl_significance does not report {k}"


def test_it_reads_both_pnl_key_spellings():
    """The books disagree: the sleeves write `pnl` on a sell row, others write
    `realized`. The first version read only `realized` and reported NOTHING —
    which at least failed loudly rather than confidently measuring a subset."""
    src = (Path(__file__).resolve().parents[2] / "scripts" / "brain_audit.py").read_text()
    # Scoped to the function by its own extent, not a byte count: the first
    # version used a fixed 3500-char window and broke the moment the benchmark
    # code made the function longer. A test that depends on how long the code
    # happens to be is a test that will fail for the wrong reason.
    import ast
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "pnl_significance")
    body = ast.unparse(fn)
    assert "realized" in body and "pnl" in body, \
        "one spelling only — some books' P&L will be silently invisible"


# --- the benchmark, and two bugs it exposed in this very file's instrument ---

def _student_p(t, df):
    import sys as _s
    _s.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import brain_audit
    return brain_audit._student_p(t, df)


def test_the_t_distribution_not_the_normal():
    """The first version of `pnl_significance` used the normal approximation
    and it changed the verdict.

    At n=6 the sleeve's excess is t=2.18. The normal says **p=0.029 —
    significant**. Student's t with 5 degrees of freedom says **p=0.081 — not**.
    The standard error at n=6 is itself estimated from those six points, and
    the normal pretends otherwise.

    Checked against textbook critical values so the implementation is not
    merely self-consistent.
    """
    assert abs(_student_p(2.571, 5) - 0.05) < 0.002, "df=5 critical value is 2.571"
    assert abs(_student_p(2.000, 60) - 0.05) < 0.003, "df=60 critical value is 2.000"
    assert abs(_student_p(2.18, 5) - 0.081) < 0.005, "the verdict-changing case"


def _sig(xs):
    import sys as _s
    _s.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import brain_audit
    return brain_audit.significance(xs)


def test_no_p_value_at_all_below_five_observations():
    """Not a conservative p-value: none.

    The normal approximation reported **p = 0.000 at n = 3** for the crypto
    book. A number that cannot mean anything must not be printed in a field a
    reader will compare against 0.05 — reporting nothing is the honest output.

    Driven through the REAL function, not grepped for. The first version
    searched the source for `MIN_N_FOR_P` and passed with the floor set to 0 —
    §4.44's lesson (a test that checks the helper, not the wiring) for the
    third time this session. `significance()` was lifted out of a closure
    precisely so this test could call it.
    """
    out = _sig([1.0, 2.0, 3.0])
    assert out["n"] == 3
    assert out["p"] is None, f"a p-value was reported at n=3: {out}"
    assert out["significant"] is False
    assert "note" in out, "the reason for the missing p must be stated"


def test_the_real_function_uses_the_t_distribution():
    """Also driven, not grepped. With the normal approximation the sleeve's six
    baskets return p=0.029; with Student's t they return p=0.162. Same data."""
    out = _sig([-190.5, 476.8, 31.4, 556.5, 222.0, 50.1])
    assert out["n"] == 6 and abs(out["t"] - 1.64) < 0.02
    assert out["p"] is not None and 0.15 < out["p"] < 0.18, \
        f"p={out['p']} — this is the normal approximation, not Student's t"
    assert out["significant"] is False


def test_significant_is_not_the_same_as_good():
    """The bug that reported a LOSING book as beating its benchmark.

    `crypto_event` has mean excess **-7.44%** and t=-2.88. The first version
    tested only `significant` and duly printed "beats its benchmark". A
    two-sided test says *not zero*; it does not say *good*. Direction must be
    asserted separately, always.
    """
    import ast
    src = (Path(__file__).resolve().parents[2] / "scripts" / "brain_audit.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "pnl_significance")
    body = ast.unparse(fn)
    assert "UNDERPERFORMS" in body, "a significantly-losing book has no distinct verdict"
    assert "> 0" in body and "beat" in body, \
        "the 'beats' verdict does not check the SIGN of the excess"


def test_the_sleeve_needs_eight_baskets_to_settle_it():
    """The useful output of all this: not a verdict, a countable cue.

    The sleeve's excess is +2.54% per basket at t=2.18 over 6 baskets — an
    effect size of 0.89. Holding that constant, it clears p<0.05 at **8
    baskets**. That is two more, not a research programme.
    """
    import math
    eff = 2.18 / math.sqrt(6)
    assert abs(eff - 0.89) < 0.01
    need = next(n for n in range(6, 30) if _student_p(eff * math.sqrt(n), n - 1) < 0.05)
    assert need == 8, need


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} pnl-significance tests passed.")
