from datetime import datetime, timedelta

from stockbot.broker.base import Quote
from stockbot.market_calendar import KST
from stockbot.risk.rules import OrderIntent

NOW = datetime(2026, 12, 2, 8, 0, tzinfo=KST)   # market closed (no stale checks)
OPEN = datetime(2026, 12, 2, 23, 30, tzinfo=KST)


def quotes(*prices, prev_close=100.0, ts=NOW):
    seq = list(prices)

    def fn(t):
        p = seq.pop(0) if len(seq) > 1 else seq[0]
        return Quote(ticker=t, price=p, ts=ts, prev_close=prev_close)
    return fn


def _i(t, side, qty, kind, key=None, **kw):
    return OrderIntent(ticker=t, side=side, qty=qty, kind=kind, reason="test", idempotency_key=key or f"k:{kind}:{t}", **kw)


def buy(t, qty, key=None): return _i(t, "buy", qty, "new_buy", key)
def rebuy(t, qty, limit, expires): return _i(t, "buy", qty, "rebuy", limit_price=limit, expires_at=expires)
def buy_i(t="B"): return _i(t, "buy", 1, "new_buy")
def add_i(t="B"): return _i(t, "buy", 1, "add")
def switch_buy_i(t="X"): return _i(t, "buy", 1, "switch_buy")
def sell_i(t="A"): return _i(t, "sell", 1, "sell")
def stop_i(t="A"): return _i(t, "sell", 1, "stop_loss")
def rebuy_i(t="A"): return _i(t, "buy", 1, "rebuy", limit_price=90, expires_at=NOW + timedelta(days=30))
