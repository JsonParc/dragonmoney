"""Continuous news watch for held positions; emergency debates only on cross-verified news (spec §7.1a)."""
from __future__ import annotations

from datetime import datetime, timedelta

from stockbot.data.news import map_tickers
from stockbot.data.universe import sector_of
from stockbot.market_calendar import KST, is_market_open
from stockbot.sentiment.impact import TAG_SECTOR_IMPACT, assess
from stockbot.settings_store import get_kv, set_kv

EMERGENCY_COOLDOWN = timedelta(hours=2)


def ingest_news(deps, now: datetime, held: list[str]) -> int:
    """Fetch from every source, score, tag, store and re-verify. Returns number of new items."""
    since = now - timedelta(hours=24)
    items, ok = [], True
    for src in deps.news_sources:
        try:
            items += src.fetch(since, held)
        except Exception as e:
            ok = False
            deps.health.record("news", False, f"{type(src).__name__}: {e}", now)
    for it in items:
        if not it.tickers:
            it.tickers = map_tickers(f"{it.title} {it.summary}")
    if items:
        scores = deps.scorer.score([f"{i.title}. {i.summary}" for i in items])
        items = [assess(i, s) for i, s in zip(items, scores)]
    added = deps.news.add(items)
    deps.verifier.update(now)
    if ok:
        deps.health.record("news", True, f"{added} new", now)
    return added


class NewsWatcher:
    def __init__(self, deps):
        self.d = deps

    def _kv(self, key, default=None):
        with self.d.session_factory() as s:
            return get_kv(s, key, default)

    def _set(self, key, value):
        with self.d.session_factory() as s:
            set_kv(s, key, value)
            s.commit()

    def _relevant(self, cluster, ticker: str) -> bool:
        sector = sector_of(ticker)
        return ticker in cluster.tickers or any(TAG_SECTOR_IMPACT.get(t, {}).get(sector, 0) for t in cluster.tags)

    def poll(self, now: datetime) -> list[int]:
        from stockbot.pipeline.context import PriceMarket, next_open_after, portfolio_view
        from stockbot.pipeline.daily import run_debate
        from stockbot.risk.rules import apply_risk, circuit_breaker_tripped

        d = self.d
        cfg = d.runtime()
        held = list(d.broker.positions())
        before = {c.id: c.verification for c in d.verifier.recent(now, 48)}
        ingest_news(d, now, held)
        if not held:
            return []
        clusters = [c for c in d.verifier.recent(now, 48) if before.get(c.id) != c.verification]
        as_of = now.astimezone(KST).date()
        mkt = PriceMarket(d.prices, as_of)
        debates: list[int] = []
        for c in sorted(clusters, key=lambda c: -c.severity):
            if c.severity < cfg.severity_threshold or c.verification == "contradicted":
                continue
            targets = [t for t in held if self._relevant(c, t)]
            if not targets:
                continue
            if c.verification == "unconfirmed":
                if not self._kv(f"notified_cluster:{c.id}"):
                    self._set(f"notified_cluster:{c.id}", True)
                    d.notifier.send(f"확인 중: [미확인·출처 {c.independent_sources}곳] {c.headline}\n"
                                    f"관련 보유: {', '.join(targets)} — 다른 매체에서 확인되면 긴급 토론을 엽니다.")
                continue
            for t in targets:
                last = self._kv(f"last_emergency:{t}")
                if last and now - datetime.fromisoformat(last) < EMERGENCY_COOLDOWN:
                    continue
                self._set(f"last_emergency:{t}", now.isoformat())
                pf = portfolio_view(d, mkt)
                did, result, intents = run_debate(d, t, as_of, "emergency", pf, mkt, cfg, news_as_of=now)
                debates.append(did)
                out = apply_risk(intents, pf, mkt, cfg.budget_usd, cfg.risk, cfg.mode,
                                 circuit_breaker_tripped(pf, cfg.risk))
                sells = [i for i in out.accepted if i.side == "sell"]
                buys = [i for i in out.accepted if i.side == "buy"]
                action = result.resolved.action.value if result.resolved else "결정 없음"
                if is_market_open(now) and sells:
                    res = d.executor.execute_now(sells, now)
                    done = ", ".join(f"{r.ticker} {r.fill_qty}주 {r.status}" for r in res)
                    d.executor.stage(buys, cfg.mode, cfg.rebuy_auto, next_open_after(now))
                    d.notifier.send(f"🚨 긴급 토론 #{did} ({t}): {action}\n뉴스: {c.headline}\n방어 실행: {done}")
                else:
                    d.executor.stage(sells + buys, cfg.mode, cfg.rebuy_auto, next_open_after(now))
                    d.notifier.send(f"🚨 긴급 토론 #{did} ({t}): {action}\n뉴스: {c.headline}\n다음 장 시작 때 실행합니다.")
        return debates
