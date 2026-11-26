"""News collection from many free sources, stored with dedupe and as-of reads."""
from __future__ import annotations

import re
import tomllib
from calendar import timegm
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Protocol
from urllib.parse import quote_plus, urlparse

import feedparser
import httpx
from pydantic import BaseModel
from sqlalchemy import select

from stockbot.data.universe import load_universe
from stockbot.models import NewsRow

_STATIC = Path(__file__).resolve().parents[3] / "data_static"
USER_AGENT = "stockbot-research-client/0.1"


class NewsItem(BaseModel):
    url: str
    title: str
    summary: str = ""
    source: str = ""
    domain: str = ""
    wire: str | None = None
    published_at: datetime
    tickers: list[str] = []
    tags: list[str] = []
    sentiment: float = 0.0
    severity: int = 0
    id: int | None = None


class FeedSpec(BaseModel):
    name: str
    url: str
    tier: int = 2


class NewsSource(Protocol):
    def fetch(self, since: datetime, tickers: list[str]) -> list[NewsItem]: ...


# ---------------------------------------------------------------- helpers
def domain_of(url: str) -> str:
    host = urlparse(url).netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


_WIRES = [("Reuters", r"\(reuters\)"), ("AP", r"\(ap\)|associated press"), ("Bloomberg", r"\(bloomberg\)"),
          ("Dow Jones", r"dow jones newswires"), ("AFP", r"\(afp\)")]


def detect_wire(text: str) -> str | None:
    low = text.lower()
    for name, pat in _WIRES:
        if re.search(pat, low):
            return name
    return None


def norm_title(t: str) -> str:
    return " ".join(re.sub(r"[^0-9a-z가-힣 ]", " ", t.lower()).split())


_SUFFIX = r"\b(inc|incorporated|corp|corporation|co|company|companies|ltd|plc|holdings|holding|group|the|class [a-c]|n\.?v|s\.?a|lp|llc|international|technologies|technology)\b"
_COMMON = {"news", "southern", "target", "ball", "general", "american", "first", "best", "public", "united",
           "global", "dominion", "eastern", "state", "street", "republic", "progressive", "principal", "fox",
           "booking", "match", "visa", "match group", "ford", "gap", "realty", "copart"}
_EXTRA = {"google": "GOOGL", "facebook": "META", "meta": "META", "jpmorgan": "JPM", "exxon": "XOM",
          "berkshire": "BRK-B", "tesla": "TSLA", "amazon": "AMZN", "microsoft": "MSFT", "nvidia": "NVDA"}


@lru_cache
def alias_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for e in load_universe():
        name = re.sub(r"\(.*?\)", " ", e.name.lower())
        name = re.sub(_SUFFIX, " ", name.replace(".com", " "))
        name = " ".join(re.sub(r"[^0-9a-z& ]", " ", name).split())
        if len(name) >= 4 and name not in _COMMON:
            out.setdefault(name, e.ticker)
    out.update(_EXTRA)
    return out


def map_tickers(text: str, restrict: list[str] | None = None) -> list[str]:
    low = " " + " ".join(re.sub(r"[^0-9a-z& ]", " ", text.lower()).split()) + " "
    found = {t for alias, t in alias_map().items() if f" {alias} " in low}
    found |= set(re.findall(r"\((?:nasdaq|nyse)\s*:\s*([A-Z.\-]{1,6})\)", text, flags=re.I))
    found |= set(re.findall(r"\$([A-Z]{1,5})\b", text))
    found = {f.upper().replace(".", "-") for f in found}
    if restrict:
        found = {f for f in found if f in set(restrict)} or found
    return sorted(found)


def _entry_time(e) -> datetime | None:
    st = e.get("published_parsed") or e.get("updated_parsed")
    return datetime.fromtimestamp(timegm(st), tz=timezone.utc) if st else None


def _clean_html(s: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", s or "").split())


# ---------------------------------------------------------------- sources
class RssSource:
    def __init__(self, feeds: list[FeedSpec], client: httpx.Client | None = None):
        self.feeds = feeds
        self.client = client or httpx.Client(timeout=20, headers={"User-Agent": USER_AGENT}, follow_redirects=True)

    def fetch(self, since: datetime, tickers: list[str]) -> list[NewsItem]:
        out: list[NewsItem] = []
        for f in self.feeds:
            try:
                parsed = feedparser.parse(self.client.get(f.url).text)
            except httpx.HTTPError:
                continue
            for e in parsed.entries:
                ts = _entry_time(e)
                link = e.get("link", "")
                if not ts or ts < since or not link:
                    continue
                title, summary = _clean_html(e.get("title", "")), _clean_html(e.get("summary", ""))
                out.append(NewsItem(url=link, title=title, summary=summary[:1000], source=f.name,
                                    domain=domain_of(link), wire=detect_wire(f"{title} {summary}"),
                                    published_at=ts, tickers=map_tickers(f"{title} {summary}")))
        return out


MACRO_QUERIES = ["stock market", "oil prices", "federal reserve rates", "inflation report", "war markets",
                 "tariffs", "recession", "bank crisis"]


class GoogleNewsSource:
    """Google News RSS search; keeps the original publisher's domain for cross-checking."""

    def __init__(self, queries: list[str] | None = None, client: httpx.Client | None = None):
        self.queries = queries if queries is not None else MACRO_QUERIES
        self.client = client or httpx.Client(timeout=20, headers={"User-Agent": USER_AGENT}, follow_redirects=True)

    def fetch(self, since: datetime, tickers: list[str]) -> list[NewsItem]:
        names = {t: n for n, t in alias_map().items()}
        queries = list(self.queries) + [names.get(t, t) for t in tickers]
        out: list[NewsItem] = []
        for q in queries:
            url = f"https://news.google.com/rss/search?q={quote_plus(q)}+when:1d&hl=en-US&gl=US&ceid=US:en"
            try:
                parsed = feedparser.parse(self.client.get(url).text)
            except httpx.HTTPError:
                continue
            for e in parsed.entries:
                ts = _entry_time(e)
                if not ts or ts < since:
                    continue
                src = e.get("source") or {}
                publisher = src.get("title", "")
                dom = domain_of(src.get("href", "")) or domain_of(e.get("link", ""))
                title = _clean_html(e.get("title", ""))
                if publisher and title.endswith(f" - {publisher}"):
                    title = title[: -len(publisher) - 3]
                out.append(NewsItem(url=e.get("link", ""), title=title, source=publisher or "Google News",
                                    domain=dom, wire=detect_wire(title), published_at=ts, tickers=map_tickers(title)))
        return out


class FinnhubSource:
    BASE = "https://finnhub.io/api/v1"

    def __init__(self, api_key: str, client: httpx.Client | None = None):
        self.key = api_key
        self.client = client or httpx.Client(timeout=20)

    def _items(self, rows: list[dict], default_tickers: list[str]) -> list[NewsItem]:
        out = []
        for r in rows:
            url = r.get("url", "")
            if not url:
                continue
            text = f"{r.get('headline', '')} {r.get('summary', '')}"
            rel = [x.strip() for x in str(r.get("related", "")).split(",") if x.strip()]
            out.append(NewsItem(url=url, title=r.get("headline", ""), summary=r.get("summary", "")[:1000],
                                source=r.get("source", "Finnhub"), domain=domain_of(url), wire=detect_wire(text),
                                published_at=datetime.fromtimestamp(int(r.get("datetime", 0)), tz=timezone.utc),
                                tickers=rel or default_tickers or map_tickers(text)))
        return out

    def fetch(self, since: datetime, tickers: list[str]) -> list[NewsItem]:
        out: list[NewsItem] = []
        frm, to = since.date().isoformat(), (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
        for t in tickers:
            try:
                r = self.client.get(f"{self.BASE}/company-news", params={"symbol": t, "from": frm, "to": to, "token": self.key})
                r.raise_for_status()
                out += self._items(r.json(), [t])
            except (httpx.HTTPError, ValueError):
                continue
        if not tickers:
            try:
                r = self.client.get(f"{self.BASE}/news", params={"category": "general", "token": self.key})
                r.raise_for_status()
                out += self._items(r.json(), [])
            except (httpx.HTTPError, ValueError):
                pass
        return [i for i in out if i.published_at >= since]


class SecEdgarSource:
    """8-K filings of held companies (tier-0 primary source)."""

    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=20, headers={"User-Agent": USER_AGENT}, follow_redirects=True)

    def fetch(self, since: datetime, tickers: list[str]) -> list[NewsItem]:
        ciks = {e.ticker: e.cik for e in load_universe() if e.cik}
        out: list[NewsItem] = []
        for t in tickers:
            cik = ciks.get(t)
            if not cik:
                continue
            url = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
                   f"&CIK={cik}&type=8-K&dateb=&owner=include&count=10&output=atom")
            try:
                parsed = feedparser.parse(self.client.get(url).text)
            except httpx.HTTPError:
                continue
            for e in parsed.entries:
                ts = _entry_time(e)
                if not ts or ts < since:
                    continue
                out.append(NewsItem(url=e.get("link", url), title=f"{t} 8-K: {_clean_html(e.get('title', ''))}",
                                    summary=_clean_html(e.get("summary", ""))[:1000], source="SEC EDGAR",
                                    domain="sec.gov", published_at=ts, tickers=[t]))
        return out


# ---------------------------------------------------------------- config
def load_feeds() -> list[FeedSpec]:
    with open(_STATIC / "news_sources.toml", "rb") as f:
        return [FeedSpec(**x) for x in tomllib.load(f).get("feeds", [])]


@lru_cache
def load_source_tiers() -> dict[str, int]:
    with open(_STATIC / "news_sources.toml", "rb") as f:
        return dict(tomllib.load(f).get("tiers", {}))


def tier_of(domain: str, tiers: dict[str, int] | None = None) -> int:
    tiers = tiers if tiers is not None else load_source_tiers()
    d = domain.lower()
    while d:
        if d in tiers:
            return tiers[d]
        if "." not in d:
            break
        d = d.split(".", 1)[1]
    return 3


# ---------------------------------------------------------------- store
def _naive_utc(ts: datetime) -> datetime:
    return ts.astimezone(timezone.utc).replace(tzinfo=None) if ts.tzinfo else ts


def _to_item(r: NewsRow) -> NewsItem:
    return NewsItem(id=r.id, url=r.url, title=r.title, summary=r.summary or "", source=r.source or "",
                    domain=r.domain or "", wire=r.wire, published_at=r.published_at.replace(tzinfo=timezone.utc),
                    tickers=r.tickers or [], tags=r.tags or [], sentiment=r.sentiment or 0.0, severity=r.severity or 0)


class NewsStore:
    def __init__(self, session_factory):
        self._sf = session_factory

    def add(self, items: list[NewsItem]) -> int:
        added = 0
        with self._sf() as s:
            for it in items:
                tn = norm_title(it.title)
                dup = s.execute(select(NewsRow.id).where(
                    (NewsRow.url == it.url) | ((NewsRow.domain == it.domain) & (NewsRow.title_norm == tn))
                ).limit(1)).first()
                if dup:
                    continue
                row = NewsRow(url=it.url, title=it.title, title_norm=tn, summary=it.summary, source=it.source,
                              domain=it.domain, wire=it.wire, published_at=_naive_utc(it.published_at),
                              fetched_at=_naive_utc(datetime.now(timezone.utc)), tickers=it.tickers, tags=it.tags,
                              sentiment=it.sentiment, severity=it.severity)
                s.add(row)
                s.flush()
                it.id = row.id
                added += 1
            s.commit()
        return added

    def update_scores(self, items: list[NewsItem]) -> None:
        with self._sf() as s:
            for it in items:
                if it.id is None:
                    continue
                row = s.get(NewsRow, it.id)
                if row:
                    row.tags, row.sentiment, row.severity, row.tickers = it.tags, it.sentiment, it.severity, it.tickers
            s.commit()

    def query(self, as_of: datetime, since: datetime, tickers: list[str] | None = None,
              min_severity: int = 0) -> list[NewsItem]:
        with self._sf() as s:
            rows = s.execute(select(NewsRow).where(
                NewsRow.published_at <= _naive_utc(as_of), NewsRow.published_at >= _naive_utc(since),
                NewsRow.severity >= min_severity).order_by(NewsRow.published_at)).scalars().all()
        out = [_to_item(r) for r in rows]
        if tickers:
            want = set(tickers)
            out = [i for i in out if want & set(i.tickers)]
        return out
