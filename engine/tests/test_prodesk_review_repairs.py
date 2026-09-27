import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ai_investing.backtest.engine import Backtester
from ai_investing.brokers.shared import BookBroker
from ai_investing.execution.capital import BookLedger
from ai_investing.learning.outcome_ledger import OutcomeLedger
from ai_investing.models import Asset, AssetClass, Bar, Order, OrderStatus, Side


class _PartialVenue:
    live = True

    def __init__(self):
        self.responses = [("partial", 2, 101.0), ("filled", 5, 103.0)]

    def get_cash(self):
        return 10_000.0

    def submit(self, order, price):
        return Order(order.asset, order.side, order.qty, status=OrderStatus.PENDING,
                     id="venue-1", reason="queued")

    def fetch_fill(self, order_id):
        return self.responses.pop(0) if self.responses else None


class ProDeskReviewRepairs(unittest.TestCase):
    def test_outcome_settlement_uses_explicit_prediction(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            journal = root / "decisions.jsonl"
            ledger = OutcomeLedger(str(root / "outcomes"), "nn5")
            decision_ts = datetime.now(timezone.utc) - timedelta(days=10)
            row = {
                "ts": decision_ts.isoformat(), "day": "2026-09-01",
                "symbol": "AAA", "asset_key": "stock:AAA", "is_primary": True,
                "model_id": "nn5:artifact", "prediction_id": "nn5:artifact:stock:AAA:2026-09-01",
                "prediction": {"direction": "LONG", "target_weight": 0.4,
                               "expected_return": 0.12},
                # A conflicting nested comparator must never be selected.
                "nn3": {"expected_return": -0.9}, "price": 100.0,
                "features": {"bias": 1.0},
            }
            ledger.append_decisions(str(journal), [row])
            self.assertEqual(ledger.settle(str(journal), {"stock:AAA": 110.0}, [],
                                           now=datetime.now(timezone.utc)), 1)
            settled = json.loads((root / "outcomes" / "outcomes.jsonl").read_text())
            self.assertEqual(settled["model_id"], "nn5:artifact")
            self.assertAlmostEqual(settled["expected_return"], 0.12)
            self.assertEqual(ledger.settle(str(journal), {"stock:AAA": 110.0}, [],
                                           now=datetime.now(timezone.utc)), 0)

    def test_missing_prediction_contract_fails_loudly(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = OutcomeLedger(td, "nn")
            with self.assertRaises(ValueError):
                ledger.append_decisions(str(Path(td) / "decisions.jsonl"),
                                         [{"is_primary": True}])

    def test_partial_fill_replay_records_incremental_notional_once(self):
        with tempfile.TemporaryDirectory() as td:
            asset = Asset("AAPL", AssetClass.STOCK)
            broker = BookBroker("test", BookLedger(10_000.0),
                                stock_broker=_PartialVenue(),
                                execution_path=str(Path(td) / "executions.jsonl"))
            result = broker.submit(Order(asset, Side.BUY, 5), 100.0)
            self.assertIs(result.status, OrderStatus.PENDING)
            broker.resolve_pending()
            broker.resolve_pending()
            rows = [json.loads(line) for line in
                    (Path(td) / "executions.jsonl").read_text().splitlines()]
            self.assertEqual([r["quantity"] for r in rows], [2.0, 3.0])
            self.assertAlmostEqual(rows[0]["executed_price"], 101.0)
            self.assertAlmostEqual(rows[1]["executed_price"], (5 * 103 - 2 * 101) / 3)
            self.assertAlmostEqual(sum(r["notional"] for r in rows), 5 * 103)

    def test_backtest_alignment_uses_timestamps(self):
        bt = Backtester()
        def bar(day, close):
            return Bar(datetime.fromisoformat(day).replace(tzinfo=timezone.utc),
                       close, close, close, close, 1.0)
        aligned, length = bt._aligned({
            "stock:A": [bar("2026-04-01", 1), bar("2026-04-02", 2)],
            "stock:B": [bar("2026-04-02", 3), bar("2026-04-03", 4)],
        })
        self.assertEqual(length, 1)
        self.assertEqual(aligned["stock:A"][0].ts, aligned["stock:B"][0].ts)
        self.assertEqual(aligned["stock:A"][0].ts.day, 2)


if __name__ == "__main__":
    unittest.main()
