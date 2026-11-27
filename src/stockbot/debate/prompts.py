from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from stockbot.debate.schema import Opinion, OpinionBody, Team
from stockbot.debate.seats import Seat
from stockbot.llm.base import LLMRequest

if TYPE_CHECKING:
    from stockbot.debate.engine import DebateContext

_RULES = """규칙:
- 반드시 아래 행동 중 하나를 고른다. "모르겠다", 기권, 판단 보류는 허용되지 않는다. 보유 유지(HOLD)를 고를 때도 근거를 댄다.
- 허용 행동: {allowed}
- size_pct: BUY/ADD는 투입금 대비 비중(0~1), TRIM은 보유 수량 중 매도 비율(0~1).
- SELL_REBUY(지금 팔고 싸게 되사기)는 rebuy_price(되살 가격)를 반드시 넣는다. expected_drop_pct(예상 하락률, 음수)도 넣는다.
- SWITCH(팔고 다른 종목 매수)는 switch_to(티커)를 반드시 넣는다.
- 상대 팀의 논리가 더 설득력 있으면 입장을 바꿔도 된다. 결과가 맞았을 때만 설득 보너스가 주어지고, 틀린 쪽으로 설득하면 감점된다.
- 출력은 설명 없이 JSON 객체 하나만. 스키마:
{schema}"""

_HELD_ACTIONS = "ADD, HOLD, TRIM, SELL, SELL_REBUY, SWITCH"
_NEW_ACTIONS = "BUY, HOLD"


def _schema() -> str:
    props = OpinionBody.model_json_schema()["properties"]
    return json.dumps({k: v.get("type", v.get("anyOf", v.get("$ref", ""))) for k, v in props.items()},
                      ensure_ascii=False)


def _anon(text: str, ticker: str, as_of_iso: str) -> str:
    text = re.sub(rf"\b{re.escape(ticker)}\b", "종목 A", text)
    text = text.replace(as_of_iso, "D일")
    return re.sub(r"\b(19|20)\d{2}-\d{2}-\d{2}\b", "D일 전후", text)


def seat_prompt(seat: Seat, ctx: "DebateContext", round: int, prior: list[Opinion]) -> LLMRequest:
    allowed = _HELD_ACTIONS if ctx.holding else _NEW_ACTIONS
    system = (f"너는 미국 주식 매매 토론에 참여한 {'차트팀' if seat.team == Team.CHART else '뉴스팀'}의 "
              f"'{seat.role_ko}'다.\n{seat.persona}\n\n" + _RULES.format(allowed=allowed, schema=_schema()))
    lines = [f"종목: {ctx.ticker} ({ctx.sector})", f"기준일: {ctx.as_of.isoformat()}", f"현재가: {ctx.last_price:.2f}",
             f"토론 종류: {'긴급 토론' if ctx.kind == 'emergency' else '정기 토론'}"]
    if ctx.product_note:
        lines.append(f"상품 정보: {ctx.product_note} — 레버리지·인버스 ETF는 매일 재조정되어 오래 들고 있으면 "
                     "기초지수가 제자리여도 가격이 감쇠할 수 있다. 보유 기간과 변동성을 반드시 고려할 것.")
    if ctx.holding:
        h = ctx.holding
        lines.append(f"보유 중: {h.qty}주, 평단 {h.avg_price:.2f}, 손익 {h.pnl_pct:+.1%}")
    else:
        lines.append("미보유 (신규 매수 검토)")
    if seat.team == Team.CHART:
        lines.append("\n[차트 신호]")
        lines += [f"- {s}" for s in ctx.chart_signals] or ["- 특이 신호 없음"]
        lines.append("[지표] " + ", ".join(f"{k}={v:.2f}" for k, v in ctx.indicator_summary.items()))
        if seat.uses_image and ctx.chart_png:
            lines.append("(첨부된 6개월 차트 이미지도 참고)")
    else:
        lines.append("\n[뉴스 (교차검증 상태 포함)]")
        lines += [f"- {n}" for n in ctx.news_digest] or ["- 관련 뉴스 없음"]
        lines.append("[거시]")
        lines += [f"- {m}" for m in ctx.macro_digest] or ["- 데이터 없음"]
        if seat.seat_id == "news_fundamental":
            lines.append("[재무제표 지표]")
            lines += [f"- {x}" for x in ctx.fundamentals_digest] or ["- 재무 데이터 없음"]
        if seat.seat_id == "news_case" or ctx.case_digest:
            lines.append("[과거 유사 사례]")
            lines.append(ctx.case_digest or "- 사례집 미구축 (일반적 패턴으로 추정할 것)")
    if ctx.scoreboard_text:
        lines.append("\n[점수판]\n" + ctx.scoreboard_text)
    if round >= 1 and prior:
        lines.append(f"\n[직전 라운드 의견 — 반박 라운드 {round}]")
        for o in prior:
            team = "차트팀" if o.team == Team.CHART else "뉴스팀"
            status = "" if o.valid else " (무효)"
            lines.append(f"- {o.seat_id} ({team}){status}: {o.action} 확신 {o.confidence:.2f} — {o.rationale}")
        lines.append("상대 팀 근거를 검토하고 최종 입장을 JSON으로 다시 제출하라.")
    user = "\n".join(lines)
    if ctx.anonymize:
        user = _anon(user, ctx.ticker, ctx.as_of.isoformat())
    image = ctx.chart_png if (seat.uses_image and seat.team == Team.CHART) else None
    return LLMRequest(system=system, user=user, image_png=image, max_tokens=700)


def referee_prompt(ctx: "DebateContext", final: list[Opinion], direction: str | None, deadlock: bool) -> LLMRequest:
    lines = [f"종목 {ctx.ticker}, 기준일 {ctx.as_of.isoformat()} 토론 최종 의견:"]
    for o in final:
        lines.append(f"- {o.seat_id}: {o.action} ({o.confidence:.2f}) {o.rationale}")
    lines.append(f"결론: {'교착(결정 없음)' if deadlock else direction or '결정 없음'}")
    lines.append("양측 핵심 논거와 결론, 리스크를 한국어 3~4문장으로 요약하라.")
    user = "\n".join(lines)
    if ctx.anonymize:
        user = _anon(user, ctx.ticker, ctx.as_of.isoformat())
    return LLMRequest(system="너는 투자 토론의 심판이자 리스크 관리자다. 투표권은 없고 공정하게 요약한다.",
                      user=user, max_tokens=400, want_json=False)
