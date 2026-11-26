"""Cross-source news verification: group stories about the same event, count independent outlets,
and label each group confirmed / unconfirmed / contradicted (spec §7.1a)."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Callable, Literal

from pydantic import BaseModel
from sqlalchemy import select

from stockbot.data.news import NewsItem, _naive_utc, _to_item, tier_of
from stockbot.models import NewsClusterRow, NewsRow

Verification = Literal["confirmed", "unconfirmed", "contradicted"]
LABEL_KO = {"confirmed": "확인됨", "unconfirmed": "미확인", "contradicted": "반박됨"}

DENIAL = [r"\bden(y|ies|ied)\b.{0,40}\b(reports?|rumou?rs?|claims?|allegations?)\b",
          r"\b(reports?|rumou?rs?|claims?)\b.{0,30}\b(false|untrue|baseless|inaccurate)\b",
          r"\bfalse reports?\b", r"\bfake news\b", r"\bhoax\b", r"\bnot true\b", r"\bunfounded\b",
          "보도를 부인", "사실무근", "가짜 뉴스", "루머일 뿐"]
_STOP = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "as", "at", "by", "after", "before", "with",
         "from", "is", "are", "be", "will", "its", "it", "this", "that", "over", "amid", "into", "new", "says",
         "say", "said", "report", "reports", "reported", "us", "u.s."}


class ClusterRow(BaseModel):
    id: int
    headline: str
    tickers: list[str]
    tags: list[str]
    verification: Verification
    independent_sources: int
    best_tier: int
    severity: int
    first_seen: datetime
    last_seen: datetime


def _tokens(text: str) -> set[str]:
    out = set()
    for w in re.sub(r"[^0-9a-z가-힣% ]", " ", text.lower()).split():
        if w in _STOP:
            continue
        if len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.add(w)
    return out


def is_denial(it: NewsItem) -> bool:
    low = f"{it.title} {it.summary}".lower()
    return any(re.search(p, low) for p in DENIAL)


def similar(a: NewsItem, b: NewsItem, embed: Callable[[str], list[float]] | None = None) -> float:
    if embed is not None:
        va, vb = embed(a.title), embed(b.title)
        num = sum(x * y for x, y in zip(va, vb))
        den = (sum(x * x for x in va) ** 0.5) * (sum(y * y for y in vb) ** 0.5)
        return num / den if den else 0.0
    ta, tb = _tokens(a.title), _tokens(b.title)
    return len(ta & tb) / len(ta | tb) if ta | tb else 0.0


def is_syndicated(a: NewsItem, b: NewsItem) -> bool:
    if a.wire and a.wire == b.wire:
        return True
    ta, tb = _tokens(f"{a.title} {a.summary}"), _tokens(f"{b.title} {b.summary}")
    return bool(ta | tb) and len(ta & tb) / len(ta | tb) >= 0.95


def cluster(items: list[NewsItem], window_hours: int = 24, threshold: float = 0.6,
            embed: Callable[[str], list[float]] | None = None) -> list[list[NewsItem]]:
    window = timedelta(hours=window_hours)
    groups: list[list[NewsItem]] = []
    for it in sorted(items, key=lambda x: x.published_at):
        best, best_sim = None, 0.0
        for g in groups:
            for m in g:
                if abs(it.published_at - m.published_at) > window:
                    continue
                sim = similar(it, m, embed)
                need = threshold
                if (is_denial(it) or is_denial(m)) and set(it.tickers) & set(m.tickers):
                    need = min(threshold, 0.3)
                if sim >= need and sim > best_sim:
                    best, best_sim = g, sim
        if best is None:
            groups.append([it])
        else:
            best.append(it)
    return groups


def independent_sources(group: list[NewsItem]) -> int:
    parent = list(range(len(group)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(group)):
        for j in range(i + 1, len(group)):
            if group[i].domain == group[j].domain or is_syndicated(group[i], group[j]):
                parent[find(i)] = find(j)
    return len({find(i) for i in range(len(group))})


def verify(group: list[NewsItem], tiers: dict[str, int] | None = None) -> Verification:
    tier = {id(it): tier_of(it.domain, tiers) for it in group}
    if any(is_denial(it) and tier[id(it)] <= 1 for it in group):
        return "contradicted"
    if any(tier[id(it)] == 0 for it in group):
        return "confirmed"
    reputable = [it for it in group if tier[id(it)] <= 2]
    if independent_sources(reputable) >= 2:
        return "confirmed"
    return "unconfirmed"


def digest_line(c: ClusterRow) -> str:
    return f"[{LABEL_KO[c.verification]}·출처 {c.independent_sources}곳] {c.headline}"


def _to_cluster(r: NewsClusterRow) -> ClusterRow:
    return ClusterRow(id=r.id, headline=r.headline, tickers=r.tickers or [], tags=r.tags or [],
                      verification=r.verification, independent_sources=r.independent_sources,
                      best_tier=r.best_tier, severity=r.severity,
                      first_seen=r.first_seen.replace(tzinfo=timezone.utc),
                      last_seen=r.last_seen.replace(tzinfo=timezone.utc))


class NewsVerifier:
    def __init__(self, session_factory, tiers: dict[str, int] | None = None, window_hours: int = 24,
                 embed: Callable[[str], list[float]] | None = None):
        self._sf = session_factory
        self.tiers = tiers
        self.window_hours = window_hours
        self.embed = embed

    def update(self, as_of: datetime) -> list[ClusterRow]:
        since = as_of - timedelta(hours=self.window_hours * 2)
        changed: list[ClusterRow] = []
        with self._sf() as s:
            rows = s.execute(select(NewsRow).where(NewsRow.published_at <= _naive_utc(as_of),
                                                   NewsRow.published_at >= _naive_utc(since))).scalars().all()
            by_id = {r.id: r for r in rows}
            items = [_to_item(r) for r in rows]
            for g in cluster(items, self.window_hours, embed=self.embed):
                members = [by_id[i.id] for i in g]
                status = verify(g, self.tiers)
                tiers = [tier_of(i.domain, self.tiers) for i in g]
                best_tier = min(tiers)
                head = min(g, key=lambda i: (tier_of(i.domain, self.tiers), i.published_at)).title
                fields = dict(
                    headline=head, verification=status, independent_sources=independent_sources(g),
                    best_tier=best_tier, severity=max(i.severity for i in g),
                    tickers=sorted({t for i in g for t in i.tickers}), tags=sorted({t for i in g for t in i.tags}),
                    first_seen=min(_naive_utc(i.published_at) for i in g),
                    last_seen=max(_naive_utc(i.published_at) for i in g),
                )
                existing = sorted({m.cluster_id for m in members if m.cluster_id is not None})
                row = s.get(NewsClusterRow, existing[0]) if existing else None
                if row is None:
                    row = NewsClusterRow(**fields)
                    s.add(row)
                    s.flush()
                    is_change = True
                else:
                    is_change = row.verification != status
                    for k, v in fields.items():
                        setattr(row, k, v)
                for m in members:
                    m.cluster_id = row.id
                if is_change:
                    changed.append(_to_cluster(row))
            s.commit()
        return changed

    def cluster_of(self, news_id: int) -> ClusterRow | None:
        with self._sf() as s:
            r = s.get(NewsRow, news_id)
            c = s.get(NewsClusterRow, r.cluster_id) if r and r.cluster_id else None
            return _to_cluster(c) if c else None

    def recent(self, as_of: datetime, hours: int = 72, tickers: list[str] | None = None) -> list[ClusterRow]:
        with self._sf() as s:
            rows = s.execute(select(NewsClusterRow).where(
                NewsClusterRow.last_seen <= _naive_utc(as_of),
                NewsClusterRow.last_seen >= _naive_utc(as_of - timedelta(hours=hours)))).scalars().all()
        out = [_to_cluster(r) for r in rows]
        if tickers:
            out = [c for c in out if set(tickers) & set(c.tickers)]
        return sorted(out, key=lambda c: (-c.severity, c.last_seen))
