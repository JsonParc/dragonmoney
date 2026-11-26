import pytest
from news_helpers import item

from stockbot.sentiment.impact import assess, relevance
from stockbot.sentiment.scorers import KeywordScorer

WAR = "Oil prices surge as war breaks out in Middle East"


def test_war_oil_headline():
    it = assess(item(title=WAR), sentiment=KeywordScorer().score([WAR])[0])
    assert it.sentiment < 0 and {"geopolitical", "oil_shock"} <= set(it.tags) and it.severity >= 4
    assert relevance(it, "NVDA", "Information Technology") == 1
    assert relevance(it, "XOM", "Energy") == 1


def test_direct_mention_relevance():
    it = assess(item(title="Nvidia beats earnings", tickers=["NVDA"]), 0.5)
    assert relevance(it, "NVDA", "Information Technology") == 2
    assert "earnings_beat" in it.tags


def test_neutral_headline_low_severity():
    it = assess(item(title="Company announces new office location"), 0.0)
    assert it.severity <= 1 and it.tags == []
    assert relevance(it, "NVDA", "Information Technology") == 0


def test_keyword_scorer_range():
    s = KeywordScorer().score(["Shares rally after upgrade", "Stocks crash on recession fears", "Weather is nice"])
    assert s[0] > 0 and s[1] < 0 and s[2] == 0 and all(-1 <= x <= 1 for x in s)


@pytest.mark.slow
def test_finbert():
    pytest.importorskip("transformers")
    from stockbot.sentiment.scorers import FinBertScorer

    s = FinBertScorer().score(["Profits soared to a record", "The company went bankrupt"])
    assert s[0] > 0 > s[1]
