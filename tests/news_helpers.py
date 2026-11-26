from datetime import datetime, timezone

from stockbot.data.news import NewsItem

_n = 0


def dt(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


def item(title="Some headline", url=None, domain="cnbc.com", published_at=None, tickers=None, wire=None, summary=""):
    global _n
    _n += 1
    return NewsItem(
        url=url or f"https://{domain}/a/{_n}",
        title=title,
        summary=summary,
        source=domain,
        domain=domain,
        wire=wire,
        published_at=published_at or dt(2024, 3, 1, 12),
        tickers=tickers or [],
    )
