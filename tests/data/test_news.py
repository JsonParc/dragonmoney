import json

import httpx
import pytest
from news_helpers import dt, item

from stockbot.data.news import FeedSpec, FinnhubSource, GoogleNewsSource, NewsStore, RssSource, detect_wire


@pytest.fixture
def news_store(session_factory):
    return NewsStore(session_factory)


def test_query_respects_as_of(news_store):
    news_store.add([item(published_at=dt(2024, 3, 1, 10)), item(url="https://x.com/u2", published_at=dt(2024, 3, 2, 10))])
    assert len(news_store.query(as_of=dt(2024, 3, 1, 23), since=dt(2024, 2, 1))) == 1


def test_dedupe_by_url_and_same_domain_title(news_store):
    assert news_store.add([item(url="https://cnbc.com/a"), item(url="https://cnbc.com/a")]) == 1
    assert news_store.add([item(url="https://cnbc.com/b", title="Same Title "), item(url="https://cnbc.com/c", title="same title!")]) == 1


def test_same_title_other_domain_kept(news_store):
    # cross-source verification needs every outlet's copy
    assert news_store.add([item(title="Oil jumps", domain="cnbc.com"), item(title="Oil jumps", domain="marketwatch.com")]) == 2


def test_query_filters_tickers_and_severity(news_store):
    a = item(tickers=["NVDA"]); a.severity = 4
    b = item(tickers=["AAPL"]); b.severity = 1
    news_store.add([a, b])
    got = news_store.query(as_of=dt(2024, 3, 2), since=dt(2024, 2, 1), tickers=["NVDA"], min_severity=3)
    assert [g.tickers for g in got] == [["NVDA"]]


def test_detect_wire():
    assert detect_wire("NEW YORK (Reuters) - Stocks fell") == "Reuters"
    assert detect_wire("WASHINGTON (AP) — The Fed") == "AP"
    assert detect_wire("plain text") is None


RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Nvidia shares fall after export curbs</title><link>https://www.cnbc.com/n1</link>
<description>(Reuters) - Nvidia Corp fell</description><pubDate>Fri, 01 Mar 2024 12:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_rss_source_parses_and_maps_tickers():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=RSS)))
    src = RssSource([FeedSpec(name="cnbc", url="https://cnbc.test/rss", tier=1)], client=client)
    items = src.fetch(since=dt(2024, 2, 1), tickers=["NVDA"])
    assert len(items) == 1 and items[0].tickers == ["NVDA"] and items[0].domain == "cnbc.com" and items[0].wire == "Reuters"


GN = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Oil soars as conflict widens - MarketWatch</title><link>https://news.google.com/rss/articles/abc</link>
<pubDate>Fri, 01 Mar 2024 12:00:00 GMT</pubDate><source url="https://www.marketwatch.com">MarketWatch</source></item>
</channel></rss>"""


def test_google_news_uses_original_domain():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=GN)))
    items = GoogleNewsSource(queries=["oil prices"], client=client).fetch(since=dt(2024, 2, 1), tickers=[])
    assert items[0].domain == "marketwatch.com" and items[0].title == "Oil soars as conflict widens"


def test_finnhub_company_news_mapping():
    payload = [{"datetime": 1709294400, "headline": "Apple beats estimates", "summary": "s",
                "url": "https://www.reuters.com/x", "source": "Reuters", "related": "AAPL"}]
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=json.dumps(payload))))
    items = FinnhubSource("k", client=client).fetch(since=dt(2024, 2, 1), tickers=["AAPL"])
    assert items[0].tickers == ["AAPL"] and items[0].domain == "reuters.com"
