"""Demo mode: a throwaway DB filled with made-up activity so the admin UI can be viewed without keys.
Every number here is fake and labelled as such in the UI login hint."""
from __future__ import annotations

import json
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from stockbot.broker.base import Quote
from stockbot.config import Settings
from stockbot.db import init_db, make_engine, make_session_factory
from stockbot.debate.engine import DebateResult, save_result
from stockbot.debate.schema import Action, Direction, Opinion, PersuasionRecord, ResolvedAction, Team
from stockbot.models import EquitySnapshot, NewsClusterRow
from stockbot.notify import ConsoleNotifier
from stockbot.risk.rules import OrderIntent

DEMO_PASSWORD = "demo"
DEMO_PIN = "0000"
PRICES = {"NVDA": 118.2, "XOM": 112.4, "AAPL": 227.5, "MSFT": 418.0}


def _op(seat, team, rnd, action, conf, why):
    return Opinion(seat_id=seat, team=team, round=rnd, action=Action(action), confidence=conf, rationale=why)


def build_demo():
    from stockbot.broker.paper import PaperBroker
    from stockbot.data.news import NewsStore
    from stockbot.data.prices import PriceStore
    from stockbot.data.verify import NewsVerifier
    from stockbot.debate.seats import DEFAULT_SEATS
    from stockbot.execution.approvals import ApprovalQueue
    from stockbot.execution.executor import Executor
    from stockbot.health import Health
    from stockbot.llm.budget import BudgetTracker
    from stockbot.config import RuntimeConfig, ModeState
    from stockbot.pipeline.deps import Deps
    from stockbot.scoring.scoreboard import Scoreboard

    path = Path(tempfile.mkdtemp(prefix="stockbot-demo-")) / "demo.db"
    engine = make_engine(f"sqlite:///{path.as_posix()}")
    init_db(engine)
    sf = make_session_factory(engine)
    now = datetime.now(timezone.utc)
    settings = Settings(_env_file=None, web_password=DEMO_PASSWORD, pin=DEMO_PIN, secret_key="demo-secret",
                        db_url=f"sqlite:///{path.as_posix()}")
    quote = lambda t: Quote(ticker=t, price=PRICES.get(t, 100.0), ts=now, prev_close=PRICES.get(t, 100.0))  # noqa: E731
    broker = PaperBroker(sf, quote, initial_cash=10_000, slippage_bps=0, commission_rate=0)
    approvals = ApprovalQueue(sf)
    notifier = ConsoleNotifier()
    cfg = RuntimeConfig()
    deps = Deps(session_factory=sf, settings=settings, prices=PriceStore(sf, None), news=NewsStore(sf), news_sources=[],
                scorer=None, verifier=NewsVerifier(sf), engine=None,
                scoreboard=Scoreboard(sf, cfg.debate, [s.seat_id for s in DEFAULT_SEATS]), broker=broker,
                executor=Executor(sf, broker, approvals, notifier), approvals=approvals, notifier=notifier,
                health=Health(sf), budget=BudgetTracker(sf, cfg.cost), universe=list(PRICES), render_charts=False)

    for t, q in (("NVDA", 15), ("XOM", 8)):
        broker.place(OrderIntent(ticker=t, side="buy", qty=q, kind="new_buy", reason="데모",
                                 idempotency_key=f"demo:{t}"), now - timedelta(days=3))
    today = date.today()
    C, N = Team.CHART, Team.NEWS
    r0 = [_op("chart_trend", C, 0, "ADD", 0.7, "20일선 위 정배열 유지, 추세 살아있음"),
          _op("chart_volume", C, 0, "HOLD", 0.55, "거래량 평범, 세력 이탈 신호 없음"),
          _op("chart_candle", C, 0, "ADD", 0.6, "눌림목 후 아랫꼬리 양봉"),
          _op("chart_indicator", C, 0, "HOLD", 0.5, "MACD 시그널선 근처, 볼린저 중단 지지"),
          _op("news_news", N, 0, "SELL_REBUY", 0.7, "[확인됨·출처 5곳] 중동 전쟁 확산, 유가 급등"),
          _op("news_case", N, 0, "SELL_REBUY", 0.75, "과거 유사 사례 7건: 기술주 D+5 평균 -6%, 바닥 4일"),
          _op("news_macro", N, 0, "SELL", 0.65, "10년물 금리와 유가 동반 상승은 기술주에 부담"),
          _op("news_fundamental", N, 0, "HOLD", 0.55, "PER 높지만 매출 성장 +60%, 순현금이라 악재 버틸 체력 충분")]
    r1 = [_op("chart_trend", C, 1, "ADD", 0.6, "추세는 여전히 위"),
          _op("chart_volume", C, 1, "SELL_REBUY", 0.6, "뉴스팀 사례 통계 설득력 있음, 일단 빼고 되사자"),
          _op("chart_candle", C, 1, "HOLD", 0.5, "패턴상 결정적 이탈은 없음"),
          *[o.model_copy(update={"round": 1}) for o in r0[3:] if o.seat_id != "news_fundamental"],
          _op("news_fundamental", N, 1, "SELL_REBUY", 0.6, "체력은 충분하지만 유가 충격 기간엔 고PER 부담, 되사기 동의")]
    res = DebateResult(ticker="NVDA", as_of=today, kind="emergency", rounds=[r0, r1], direction=Direction.SELL_SIDE,
                       shares={Direction.BUY_SIDE: 1 / 8, Direction.HOLD: 2 / 8, Direction.SELL_SIDE: 5 / 8},
                       resolved=ResolvedAction(action=Action.SELL_REBUY, rebuy_price=109.5), deadlock=False,
                       persuasion=PersuasionRecord(persuading_team=N, switched_seats=["chart_volume", "news_fundamental"]), invalid_seats=[],
                       referee_summary="뉴스팀은 전쟁 확산과 과거 사례(평균 -6%)를 근거로 지금 팔고 $109.5에 되사자고 했고, "
                                       "차트팀 거래량 담당이 설득됐습니다. 추세가 살아 있다는 반론은 남아 있습니다.",
                       held=True)
    r_buy = [_op(s.seat_id, s.team, 0, "BUY", 0.65, "데모 근거") for s in DEFAULT_SEATS]
    res2 = DebateResult(ticker="AAPL", as_of=today, kind="regular", rounds=[r_buy], direction=Direction.BUY_SIDE,
                        shares={Direction.BUY_SIDE: 1.0, Direction.HOLD: 0.0, Direction.SELL_SIDE: 0.0},
                        resolved=ResolvedAction(action=Action.BUY, size_pct=0.1), deadlock=False,
                        persuasion=PersuasionRecord(), invalid_seats=[], referee_summary="양 팀 모두 매수에 동의했습니다.")
    with sf() as s:
        save_result(s, res)
        save_result(s, res2)
        for i in range(30):
            d = today - timedelta(days=30 - i)
            s.merge(EquitySnapshot(date=d, equity=10_000 * (1 + 0.002 * i - 0.01 * (i > 20)), cash=4_000,
                                   spy_close=500 * (1 + 0.0012 * i)))
        for head, v, n, sev in [("Middle East war widens, oil prices surge 9%", "confirmed", 5, 5),
                                ("Nvidia to be banned from China, blog claims", "contradicted", 2, 4),
                                ("Fed signals pause on rate cuts", "confirmed", 4, 3),
                                ("Apple supplier factory fire rumor", "unconfirmed", 1, 4)]:
            s.add(NewsClusterRow(first_seen=now.replace(tzinfo=None) - timedelta(hours=3),
                                 last_seen=now.replace(tzinfo=None) - timedelta(hours=1), headline=head, tickers=[],
                                 tags=["geopolitical"], verification=v, independent_sources=n, best_tier=1, severity=sev))
        s.commit()
    dec = deps.scoreboard.record_debate(2, res2, ref_price=PRICES["AAPL"])
    deps.executor.stage([OrderIntent(ticker="AAPL", side="buy", qty=4, kind="new_buy", decision_id=dec,
                                     reason="토론 결정: 신규 매수 (양 팀 합의)", idempotency_key="demo:aapl")],
                        ModeState(), True, now + timedelta(hours=8))
    deps.health.record("prices", True, "demo", now)
    deps.health.record("news", True, "demo", now)
    print(json.dumps({"demo_db": str(path), "password": DEMO_PASSWORD, "pin": DEMO_PIN}, ensure_ascii=False))
    return deps, settings
