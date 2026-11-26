from datetime import date, datetime, timedelta

from stockbot.debate.engine import DebateResult
from stockbot.debate.schema import Action, Direction, DIRECTION_OF, PersuasionRecord, ResolvedAction
from stockbot.market_calendar import KST
from stockbot.risk.guards import FillRecord
from stockbot.risk.portfolio import PortfolioView, PositionView
from stockbot.risk.rules import OrderIntent

D = date(2024, 6, 3)


class FakeMarket:
    def __init__(self, price=100.0, adv_usd=None, adv_shares=None, prices=None):
        self.price, self.prices = price, prices or {}
        self._adv_usd, self._adv_shares = adv_usd or {}, adv_shares or {}

    def last_price(self, t): return self.prices.get(t, self.price)
    def adv_usd(self, t): return self._adv_usd.get(t, 1e9)
    def adv_shares(self, t): return self._adv_shares.get(t, 1e7)


def mkt(price=100.0, **kw):
    return FakeMarket(price, **kw)


def res(action, ticker="T", **kw):
    a = Action(action)
    return DebateResult(ticker=ticker, as_of=D, kind="regular", rounds=[], direction=DIRECTION_OF[a],
                        shares={d: 0.0 for d in Direction}, resolved=ResolvedAction(action=a, **kw), deadlock=False,
                        persuasion=PersuasionRecord(), invalid_seats=[], referee_summary="")


def empty_pf(cash=10_000):
    return PortfolioView(cash=cash, positions={}, peak_equity=cash)


def pf_with(t, qty, avg, last, cash=5_000):
    return PortfolioView(cash=cash, positions={t: PositionView(ticker=t, qty=qty, avg_price=avg, last_price=last)},
                         peak_equity=cash + qty * avg)


def pf_with_n_holdings(n, cash=5_000):
    pos = {f"H{i}": PositionView(ticker=f"H{i}", qty=1, avg_price=100, last_price=100) for i in range(n)}
    return PortfolioView(cash=cash, positions=pos, peak_equity=cash + 100 * n)


def buy(t, qty, kind="new_buy"):
    return OrderIntent(ticker=t, side="buy", qty=qty, kind=kind, reason="test", idempotency_key=f"x:{kind}:{t}")


def sell(t, qty, kind="sell"):
    return OrderIntent(ticker=t, side="sell", qty=qty, kind=kind, reason="test", idempotency_key=f"x:{kind}:{t}")


def round_trips(t, n, within_days):
    out, base = [], datetime(2024, 6, 3, 23, 30, tzinfo=KST)
    for i in range(n):
        ts = base + timedelta(days=i * within_days / max(n, 1))
        out.append(FillRecord(ticker=t, side="buy", qty=1, price=100, filled_at=ts))
        out.append(FillRecord(ticker=t, side="sell", qty=1, price=100, filled_at=ts + timedelta(hours=1)))
    return out
