import json
from datetime import date, datetime, timezone

from engine_helpers import SEAT_IDS, body
from llm_fakes import ScriptedClient
from pipe_fakes import NOW, SESSION, make_deps

from stockbot.llm.base import LLMError
from stockbot.llm.router import LLMRouter
from stockbot.pipeline.daily import DailyCycle
from stockbot.report.daily_report import (
    ProposalLine,
    ReportData,
    collect_report_data,
    render_report,
    send_daily_report,
    split_message,
    write_narrative,
)
from stockbot.report.qa import answer_question, build_qa_context
from stockbot.risk.portfolio import PositionView

T = datetime(2024, 6, 4, 8, 30, tzinfo=timezone.utc)
HEADERS = ["1. 전날 시장 요약", "2. 주요 뉴스와 영향", "3. 최근 동향", "4. 보유 종목 점검", "5. 오늘의 제안"]


class _Free:
    def allow(self, c, now): return True
    def record(self, r, now): pass


def router_with(*responses):
    return LLMRouter({"reporter": [ScriptedClient(list(responses))]}, _Free())


def failing_router():
    return router_with(LLMError("down"))


def sample_data():
    return ReportData(session_date=date(2024, 6, 3), market_lines=["S&P500(SPY): 530.00 (5일 +1.0%)"],
                      top_news=["[확인됨·출처 4곳] Oil surges"], trend_lines=["강세: XLE +3.0%"],
                      holdings=[PositionView(ticker="NVDA", qty=10, avg_price=100, last_price=110)],
                      proposals=[ProposalLine(debate_id=3, ticker="AAPL", action="BUY", shares_text="매수 67%",
                                              referee_summary="차트팀 우세", approval_id=12)],
                      equity=10_500, vs_spy_pct=None, cost_state="ok")


def test_sections_in_order():
    text = render_report(sample_data(), None)
    idx = [text.index(h) for h in HEADERS]
    assert idx == sorted(idx) and "NVDA" in text and "AAPL" in text


def test_narrative_is_included():
    nar = {"market": "시장은 강했다", "proposals": "AAPL 매수를 제안"}
    text = render_report(sample_data(), nar)
    assert "시장은 강했다" in text and text.index("시장은 강했다") < text.index(HEADERS[1])


def test_fallback_when_llm_fails():
    assert write_narrative(failing_router(), sample_data(), T) is None
    assert "5. 오늘의 제안" in render_report(sample_data(), None)


def test_write_narrative_parses_json():
    r = router_with(json.dumps({"market": "m", "news": "n", "trend": "t", "holdings": "h", "proposals": "p"}))
    assert write_narrative(r, sample_data(), T)["news"] == "n"


def test_split_message():
    parts = split_message("가" * 9000, 4000)
    assert len(parts) == 3 and all(len(p) <= 4000 for p in parts)
    lines = split_message("\n".join(["줄"] * 3000), 4000)
    assert all(len(p) <= 4000 for p in lines) and "".join(lines).count("줄") == 3000


def test_qa_failure_message():
    assert answer_question(failing_router(), "왜 팔았어?", "ctx", T).startswith("지금은 답변할 수 없어요")


def test_qa_answer():
    assert answer_question(router_with("엔비디아는 악재로 팔았습니다"), "왜 팔았어?", "ctx", T) == "엔비디아는 악재로 팔았습니다"


def test_send_daily_report_end_to_end():
    deps = make_deps()
    DailyCycle(deps).post_close(SESSION, NOW)
    deps.router = failing_router()
    data = collect_report_data(deps, SESSION, NOW)
    assert data.proposals and any(p.approval_id for p in data.proposals)
    n_before = len(deps.notifier.messages)
    send_daily_report(deps, SESSION, NOW)
    sent = deps.notifier.messages[n_before:]
    assert sent[0].text.startswith("📊") and any(m.buttons for m in sent)
    assert "5. 오늘의 제안" in build_qa_context(deps, SESSION, NOW)
