import os
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_investing.brokers.base import BrokerAdapter
from ai_investing.brokers.shared import BookBroker
from ai_investing.data.inference_control import extraction_due
from ai_investing.execution.capital import BookLedger
from ai_investing.models import Asset, AssetClass, Order, OrderStatus, Position, Side


class _NoLiquidity(BrokerAdapter):
    live = True

    def __init__(self):
        self.sent = 0
        self.cash = 10_000.0

    def get_cash(self):
        return self.cash

    def get_positions(self):
        return {}

    def submit(self, order, price):
        self.sent += 1
        order.status = OrderStatus.REJECTED
        order.reason = "longport: 603059 current market lacks counterpart liquidity, market orders are not supported"
        return order


def test_backlog_shortens_feed_gate(monkeypatch, tmp_path):
    db = tmp_path / "inference_control.sqlite3"
    state = tmp_path / "state.json"
    settings = SimpleNamespace(state_path=str(state), llm_queue_enabled=False,
                               llm_queue_cache_hours=48)
    con = sqlite3.connect(db)
    con.execute("create table pending_news(id text primary key, first_seen real, payload text)")
    con.executemany("insert into pending_news values(?,?,?)",
                    [(str(i), time.time(), "{}") for i in range(121)])
    con.commit(); con.close()
    # InferenceControl derives its DB path from state_path.
    actual = tmp_path / "inference_control.sqlite3"
    assert actual.exists()
    monkeypatch.setenv("LLM_FEED_INTERVAL_SECONDS", "1200")
    monkeypatch.setenv("LLM_BACKLOG_INTERVAL_SECONDS", "300")
    monkeypatch.setenv("LLM_BACKLOG_CATCHUP_THRESHOLD", "120")
    assert extraction_due(settings)


def test_no_liquidity_rejection_is_not_resubmitted(monkeypatch):
    asset = Asset("BAESY", AssetClass.STOCK)
    venue = _NoLiquidity()
    broker = BookBroker("main", BookLedger(base=10_000,
        marks={asset.key: {"qty": 10, "avg": 10.0}}), stock_broker=venue)
    first = broker.submit(Order(asset, Side.SELL, 10), 10.0)
    second = broker.submit(Order(asset, Side.SELL, 10), 10.0)
    assert first.status is OrderStatus.REJECTED
    assert second.status is OrderStatus.REJECTED
    assert second.metadata.get("liquidity_cooldown") is True
    assert venue.sent == 1
