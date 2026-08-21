"""A change of BOOK must never read as a change in VALUE.

The failure, from the live record on 2026-08-20. The crypto sleeve moved from
an in-memory PaperBroker seeded at $10,000 to a real Binance Futures testnet
account holding $5,000, and `data/crypto_journal.jsonl` recorded:

    2026-08-19  equity 10,052.20
    2026-08-20  equity  4,999.89

Nothing was lost. But an equity journal is a CURVE, and the circuit breaker,
watchdog and daily_status all read it — so a flat book showed -50.3% in a day.

This is STATE_OF_THE_SYSTEM §4.14 ("a change of book size read as a 90%
crash"), whose fix was recorded as "declared basis, never inferred". That
declaration existed for the main runner's book and none of the four per-book
strategies had one, so §4.14 was fixed where it was observed and nowhere else.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_investing.brokers.base import BrokerAdapter
from ai_investing.brokers.paper import PaperBroker
from ai_investing.strategy.booklog import BookBasisMixin


class _Book(BookBasisMixin):
    def __init__(self, broker):
        self.broker = broker
        self._state = {}


class _Venue(BrokerAdapter):
    """Minimal adapter — the base class's default basis() is what is under test."""
    def __init__(self, name):
        self.name = name

    def get_cash(self):
        return 0.0

    def get_positions(self):
        return {}

    def submit(self, order, price):
        return order


def test_a_mark_declares_which_book_it_belongs_to():
    b = _Book(PaperBroker(cash=10_000.0))
    fields = b._basis_fields()
    assert "basis" in fields and fields["basis"], "every mark names its book"
    assert "basis_changed" not in fields, "nothing changed on the first mark"


def test_changing_the_venue_is_declared_on_the_mark_where_it_happens():
    """The exact 2026-08-20 transition: PaperBroker($10,000) -> a live venue
    holding $5,000. The step in the curve must arrive already explained."""
    b = _Book(PaperBroker(cash=10_000.0))
    first = b._basis_fields()
    paper_basis = first["basis"]

    b.broker = _Venue("binance-futures-testnet")          # the migration
    second = b._basis_fields()

    assert second["basis"] != paper_basis
    assert second["basis_changed"] == {"from": paper_basis, "to": second["basis"]}, \
        "a reader of the curve must be able to tell this step from a 50% loss"

    third = b._basis_fields()
    assert "basis_changed" not in third, "declared once, at the transition only"


def test_basis_does_not_move_when_only_the_money_does():
    """Declared, never inferred. `CircuitBreaker.ensure_basis` puts it best:
    'equity moved a lot, must be a new book' is precisely how you teach a
    safety system to explain away a real crash."""
    broker = PaperBroker(cash=10_000.0)
    b = _Book(broker)
    before = b._basis_fields()["basis"]
    broker.cash = 12.34                       # a genuine, catastrophic loss
    after = b._basis_fields()
    assert after["basis"] == before
    assert "basis_changed" not in after, "a real crash must NOT be explained away"


def test_an_unreadable_basis_degrades_without_taking_a_cycle_down():
    class _Broken(_Venue):
        def basis(self):
            raise RuntimeError("venue unreachable")

    b = _Book(_Broken("x"))
    assert b.book_basis() == "unknown"
    assert b._basis_fields()["basis"] == "unknown"


def test_all_four_books_carry_the_rule():
    """§4.10's lesson: four books each had their own phantom-valuation bug
    until one shared rule replaced them. This is that rule — every book, not
    just the one where the symptom appeared."""
    from ai_investing.strategy.crypto_book import CryptoBook
    from ai_investing.strategy.crypto_event_sleeve import CryptoEventSleeve
    from ai_investing.strategy.event_sleeve import EventSleeve
    from ai_investing.strategy.investor import Investor
    for cls in (CryptoBook, CryptoEventSleeve, EventSleeve, Investor):
        assert issubclass(cls, BookBasisMixin), f"{cls.__name__} has no declared basis"



# --- the fifth journal: the runner's own equity curve (§4.14, found 2026-08-22) ---

def test_the_runners_own_mark_declares_its_basis():
    """`BookBasisMixin` gave the four per-book strategies a declared basis and
    `stock_journal.jsonl` — the curve the watchdog and `daily_status.py`
    actually read — was still inferring.

    Caught by the §4A cue firing NEGATIVE: the first mark written after the fix
    deployed carried no `basis`. The investing book's mark on the same cycle
    did (`"basis": "BookBroker:book"`), which is what made it a real gap rather
    than a timing artefact — one of five paths, again.
    """
    import ast
    src = Path(__file__).resolve().parents[1] / "ai_investing" / "runner.py"
    fn = next(n for n in ast.walk(ast.parse(src.read_text()))
              if isinstance(n, ast.FunctionDef) and "mark" in n.name.lower()
              and "stock_journal.jsonl" in ast.unparse(n))
    body = ast.unparse(fn)
    assert '"basis"' in body or "'basis'" in body, \
        "the runner's daily mark does not declare which book it belongs to"
    assert "basis_changed" in body, \
        ("a change of basis must be marked ON the row where it happens — that "
         "is what turns a -50% step from something to explain into something "
         "already explained")
    assert "_book_basis" in body, "the basis must come from the declaration, not be inferred"


def test_the_runners_previous_basis_is_seeded_from_the_file():
    """An in-memory-only value forgets across the nightly poweroff — which on
    this box is a DAILY event — and forgetting it means the one row that should
    carry `basis_changed` silently does not. The same reasoning the day-seeding
    block right above it already gives for itself."""
    import ast
    src = (Path(__file__).resolve().parents[1] / "ai_investing" / "runner.py").read_text()
    assert 'self._last_mark_basis = row.get("basis")' in src, \
        "the previous basis is not recovered from the journal on restart"


def test_an_unreadable_basis_does_not_take_the_cycle_down():
    """The record is never worth failing a cycle over — the same rule the
    surrounding `except OSError: pass` already applies to the write."""
    src = (Path(__file__).resolve().parents[1] / "ai_investing" / "runner.py").read_text()
    i = src.index("stock_journal.jsonl")
    window = src[i:i + 3000]
    assert 'basis = "unknown"' in window, \
        "a basis that cannot be read must degrade to 'unknown', not raise"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} book-basis tests passed.")
