"""Daily briefing ("투자 설명회") sent to Telegram at 17:30 KST (spec §7.9)."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel
from sqlalchemy import select

from stockbot.data.prices import SECTOR_ETFS
from stockbot.data.verify import digest_line
from stockbot.debate.seats import REPORTER_ID
from stockbot.llm.base import LLMError, LLMRequest
from stockbot.llm.router import complete_json
from stockbot.models import DebateRow
from stockbot.pipeline.context import PriceMarket, macro_digest, portfolio_view
from stockbot.risk.portfolio import PositionView

SECTIONS = [("market", "1. 전날 시장 요약"), ("news", "2. 주요 뉴스와 영향"), ("trend", "3. 최근 동향"),
            ("holdings", "4. 보유 종목 점검"), ("proposals", "5. 오늘의 제안")]
ACTION_KO = {"BUY": "신규 매수", "ADD": "추가 매수", "HOLD": "보유 유지", "TRIM": "일부 매도", "SELL": "매도",
             "SELL_REBUY": "매도 후 되사기", "SWITCH": "종목 교체"}


class ProposalLine(BaseModel):
    debate_id: int
    ticker: str
    action: str
    shares_text: str
    referee_summary: str
    approval_id: int | None = None


class ReportData(BaseModel):
    session_date: date
    market_lines: list[str]
    top_news: list[str]
    trend_lines: list[str]
    holdings: list[PositionView]
    proposals: list[ProposalLine]
    equity: float
    vs_spy_pct: float | None = None
    cost_state: str = "ok"


class Narrative(BaseModel):
    market: str = ""
    news: str = ""
    trend: str = ""
    holdings: str = ""
    proposals: str = ""


def _trend_lines(deps, d: date) -> list[str]:
    moves = []
    for sector, etf in SECTOR_ETFS.items():
        df = deps.prices.get_bars(etf, d, 6)
        if len(df) >= 2:
            moves.append((df["close"].iloc[-1] / df["close"].iloc[0] - 1, sector, etf))
    if not moves:
        return []
    moves.sort(reverse=True)
    fmt = lambda m: f"{m[1]}({m[2]}) {m[0]:+.1%}"  # noqa: E731
    return ["5일 강세 업종: " + ", ".join(fmt(m) for m in moves[:3]),
            "5일 약세 업종: " + ", ".join(fmt(m) for m in moves[-3:][::-1])]


def collect_report_data(deps, session_date: date, now: datetime) -> ReportData:
    mkt = PriceMarket(deps.prices, session_date)
    pf = portfolio_view(deps, mkt)
    pending = {a.decision_id: a.id for a in deps.approvals.pending(now)}
    with deps.session_factory() as s:
        rows = s.execute(select(DebateRow).where(DebateRow.as_of == session_date)).scalars().all()
        from stockbot.models import DecisionRow

        dec_of = {r.debate_id: r.id for r in s.execute(select(DecisionRow).where(DecisionRow.as_of == session_date)).scalars()}
    proposals = []
    for r in rows:
        res = r.result_json or {}
        resolved = res.get("resolved") or {}
        action = resolved.get("action") or ("교착" if r.deadlock else "결정 없음")
        shares = res.get("shares") or {}
        top = max(shares.items(), key=lambda kv: kv[1]) if shares else None
        shares_text = f"{ {'buy_side': '매수', 'sell_side': '매도', 'hold': '유지'}.get(top[0], top[0])} {top[1]:.0%}" if top else ""
        proposals.append(ProposalLine(debate_id=r.id, ticker=r.ticker, action=action, shares_text=shares_text,
                                      referee_summary=r.referee_summary or "", approval_id=pending.get(dec_of.get(r.id))))
    clusters = [c for c in deps.verifier.recent(now, 30) if c.verification == "confirmed"]
    return ReportData(session_date=session_date, market_lines=macro_digest(deps, session_date),
                      top_news=[digest_line(c) for c in clusters[:5]], trend_lines=_trend_lines(deps, session_date),
                      holdings=list(pf.positions.values()), proposals=proposals, equity=pf.equity,
                      cost_state=deps.budget.state(now))


def _data_lines(data: ReportData, key: str) -> list[str]:
    if key == "market":
        return [f"- {x}" for x in data.market_lines] or ["- 시장 데이터 없음"]
    if key == "news":
        return [f"- {x}" for x in data.top_news] or ["- 확인된 주요 뉴스 없음"]
    if key == "trend":
        return [f"- {x}" for x in data.trend_lines] or ["- 데이터 없음"]
    if key == "holdings":
        if not data.holdings:
            return ["- 보유 종목 없음 (현금)"]
        return [f"- {h.ticker}: {h.qty}주, 평단 ${h.avg_price:,.2f} → ${h.last_price:,.2f} ({h.pnl_pct:+.1%})"
                for h in data.holdings]
    out = []
    for p in data.proposals:
        line = f"- {p.ticker}: {ACTION_KO.get(p.action, p.action)} (표결 {p.shares_text})"
        if p.approval_id:
            line += f" — 승인 대기 #{p.approval_id}"
        out.append(line)
        if p.referee_summary:
            out.append(f"  심판: {p.referee_summary}")
    return out or ["- 오늘은 토론 대상이 없었습니다 (신호 없음)"]


def render_report(data: ReportData, narrative: dict[str, str] | None) -> str:
    lines = [f"📊 일일 투자 설명회 — {data.session_date.isoformat()} 장 마감 기준",
             f"총자산 ${data.equity:,.2f}" + (f" (SPY 대비 {data.vs_spy_pct:+.1%})" if data.vs_spy_pct is not None else "")]
    for key, title in SECTIONS:
        lines.append("")
        lines.append(title)
        if narrative and narrative.get(key):
            lines.append(narrative[key])
        lines += _data_lines(data, key)
    if data.cost_state != "ok":
        lines.append("")
        lines.append(f"💸 AI 비용 상태: {data.cost_state}")
    lines.append("")
    lines.append("궁금한 점은 그냥 질문하세요. 오늘 토론 기록을 바탕으로 답합니다.")
    return "\n".join(lines)


def split_message(text: str, limit: int = 4000) -> list[str]:
    parts, cur = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(line[:limit])
            line = line[limit:]
        cand = f"{cur}\n{line}" if cur else line
        if len(cand) > limit:
            parts.append(cur)
            cur = line
        else:
            cur = cand
    if cur:
        parts.append(cur)
    return parts


def write_narrative(router, data: ReportData, now: datetime) -> dict[str, str] | None:
    if router is None:
        return None
    req = LLMRequest(
        system="너는 개인 투자자에게 매일 투자 설명회를 하는 애널리스트다. 쉬운 한국어로, 과장 없이, 숫자는 데이터 그대로 쓴다.",
        user=("아래 데이터로 섹션별 2~3문장 해설을 JSON으로 써라. 키: market, news, trend, holdings, proposals.\n\n"
              + render_report(data, None)),
        max_tokens=1200)
    try:
        obj, _ = complete_json(router, REPORTER_ID, req, Narrative, now)
    except LLMError:
        return None
    return obj.model_dump() if obj else None


def send_daily_report(deps, session_date: date, now: datetime) -> None:
    data = collect_report_data(deps, session_date, now)
    text = render_report(data, write_narrative(deps.router, data, now))
    for part in split_message(text):
        deps.notifier.send(part)
    for p in data.proposals:
        if p.approval_id:
            deps.notifier.send(f"승인 대기 #{p.approval_id}: {p.ticker} {ACTION_KO.get(p.action, p.action)}",
                               buttons=[("승인", f"approve:{p.approval_id}"), ("거절", f"reject:{p.approval_id}"),
                                        ("자세히", f"debate:{p.debate_id}")])
