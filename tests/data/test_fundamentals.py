import json
from datetime import datetime, timedelta, timezone

import httpx

from stockbot.data.fundamentals import FinnhubFundamentals, Fundamentals, FundamentalsStore, digest

NOW = datetime(2026, 11, 27, 6, 30, tzinfo=timezone.utc)
METRIC = {"metric": {"peTTM": 28.4, "psTTM": 7.1, "pbQuarterly": 45.2, "revenueGrowthTTMYoy": 12.3,
                     "epsGrowthTTMYoy": 9.8, "grossMarginTTM": 46.2, "operatingMarginTTM": 31.5,
                     "netProfitMarginTTM": 25.3, "roeTTM": 147.0, "totalDebt/totalEquityQuarterly": 1.8,
                     "currentRatioQuarterly": 0.9, "dividendYieldIndicatedAnnual": 0.45, "marketCapitalization": 3400000}}


def _client(payload, calls):
    def h(req):
        calls.append(str(req.url))
        return httpx.Response(200, text=json.dumps(payload))
    return httpx.Client(transport=httpx.MockTransport(h))


def test_finnhub_mapping():
    f = FinnhubFundamentals("k", client=_client(METRIC, [])).fetch("AAPL")
    assert f.pe == 28.4 and f.revenue_growth == 12.3 and f.operating_margin == 31.5
    assert f.debt_to_equity == 1.8 and f.market_cap_musd == 3400000 and f.source == "finnhub"


def test_empty_metric_is_none():
    assert FinnhubFundamentals("k", client=_client({"metric": {}}, [])).fetch("ZZZ") is None


def test_store_caches_for_a_day(session_factory):
    calls = []
    store = FundamentalsStore(session_factory, [FinnhubFundamentals("k", client=_client(METRIC, calls))])
    assert store.get("AAPL", NOW).pe == 28.4
    store.get("AAPL", NOW + timedelta(hours=5))
    assert len(calls) == 1
    store.get("AAPL", NOW + timedelta(hours=25))
    assert len(calls) == 2


def test_store_falls_back_to_next_source(session_factory):
    class Broken:
        def fetch(self, t): raise RuntimeError("down")
    store = FundamentalsStore(session_factory, [Broken(), FinnhubFundamentals("k", client=_client(METRIC, []))])
    assert store.get("AAPL", NOW).pe == 28.4


def test_digest_is_readable_korean():
    lines = digest(Fundamentals(ticker="AAPL", pe=28.4, forward_pe=24.1, revenue_growth=12.3, operating_margin=31.5,
                                debt_to_equity=1.8, roe=147.0, source="finnhub"))
    text = "\n".join(lines)
    assert "PER 28.4배" in text and "예상 24.1배" in text and "매출 성장 +12.3%" in text and "영업이익률 31.5%" in text
    assert digest(None) == ["재무 데이터 없음"]
