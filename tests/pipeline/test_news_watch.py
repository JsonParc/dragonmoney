from datetime import timedelta

from engine_helpers import SEAT_IDS, body
from pipe_fakes import MARKET_OPEN_NOW, NOW, hold, make_deps, news, series

from stockbot.models import OrderRow
from stockbot.pipeline.news_watch import NewsWatcher


def _deps_holding_nvda():
    frames = {"NVDA": series(100, 100)}
    deps = make_deps(script={s: [body("SELL")] for s in SEAT_IDS}, frames=frames)
    hold(deps, "NVDA")
    deps.clock.now = MARKET_OPEN_NOW
    return deps


def filled_sells(deps, t):
    with deps.session_factory() as s:
        return s.query(OrderRow).filter_by(ticker=t, side="sell", status="filled").count()


def test_war_news_triggers_emergency_sell_during_market():
    d = _deps_holding_nvda()
    d.news_sources[0].queue(news("War breaks out, oil prices surge 12%", "cnbc.com"),
                            news("War breaks out as oil prices surge 12 percent", "marketwatch.com"))
    ids = NewsWatcher(d).poll(MARKET_OPEN_NOW)
    assert len(ids) == 1 and filled_sells(d, "NVDA") == 1


def test_unconfirmed_rumor_only_notifies():
    d = _deps_holding_nvda()
    d.news_sources[0].queue(news("Nvidia factory destroyed in war strike", "smallblog.net"))
    assert NewsWatcher(d).poll(MARKET_OPEN_NOW) == []
    assert any(m.text.startswith("확인 중") for m in d.notifier.messages)
    later = MARKET_OPEN_NOW + timedelta(minutes=10)
    d.clock.now = later
    d.news_sources[0].queue(news("Nvidia factory destroyed in war strike, company confirms", "cnbc.com", clock=d.clock),
                            news("Nvidia factory destroyed in war strike", "marketwatch.com", clock=d.clock))
    assert len(NewsWatcher(d).poll(later)) == 1


def test_emergency_rate_limited_per_ticker():
    d = _deps_holding_nvda()
    w = NewsWatcher(d)
    d.news_sources[0].queue(news("War breaks out, oil prices surge 12%", "cnbc.com"),
                            news("War breaks out as oil prices surge 12 percent", "marketwatch.com"))
    w.poll(MARKET_OPEN_NOW)
    d.news_sources[0].queue(news("Bank collapse sparks contagion fears", "cnbc.com"),
                            news("Bank collapse sparks contagion fears across markets", "marketwatch.com"))
    assert w.poll(MARKET_OPEN_NOW + timedelta(minutes=10)) == []


def test_low_severity_ignored():
    d = _deps_holding_nvda()
    d.news_sources[0].queue(news("NVIDIA opens new office", "cnbc.com"), news("Nvidia opens a new office", "marketwatch.com"))
    assert NewsWatcher(d).poll(MARKET_OPEN_NOW) == []


def test_outside_market_stages_for_open():
    d = _deps_holding_nvda()
    d.clock.now = NOW
    d.news_sources[0].queue(news("War breaks out, oil prices surge 12%", "cnbc.com", clock=d.clock),
                            news("War breaks out as oil prices surge 12 percent", "marketwatch.com", clock=d.clock))
    assert len(NewsWatcher(d).poll(NOW)) == 1
    assert filled_sells(d, "NVDA") == 0
    with d.session_factory() as s:
        assert s.query(OrderRow).filter_by(ticker="NVDA", side="sell", status="staged").count() == 1
