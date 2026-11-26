from __future__ import annotations

from datetime import date, datetime

from stockbot.debate.seats import REPORTER_ID
from stockbot.llm.base import LLMError, LLMRequest

FAIL_TEXT = "지금은 답변할 수 없어요. 잠시 후 다시 물어봐 주세요."


def build_qa_context(deps, session_date: date, now: datetime) -> str:
    from stockbot.report.daily_report import collect_report_data, render_report

    return render_report(collect_report_data(deps, session_date, now), None)


def answer_question(router, question: str, context_text: str, now: datetime) -> str:
    if router is None:
        return FAIL_TEXT
    req = LLMRequest(
        system=("너는 이 주식 봇의 투자 설명회 진행자다. 아래 '오늘의 기록'에 있는 사실만 근거로 쉬운 한국어로 답한다. "
                "기록에 없는 내용은 모른다고 말하고, 수익을 약속하지 않는다."),
        user=f"[오늘의 기록]\n{context_text}\n\n[질문]\n{question}", max_tokens=700, want_json=False)
    try:
        text = router.complete(REPORTER_ID, req, now).text.strip()
    except LLMError:
        return FAIL_TEXT
    return text or FAIL_TEXT
