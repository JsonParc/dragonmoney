"""Telegram command handling as plain functions (no Telegram library). Shared with the web API."""
from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select

from stockbot.market_calendar import KST, is_market_open, is_trading_day, trading_session
from stockbot.models import DebateRow, OrderRow
from stockbot.pipeline.context import PriceMarket, next_open_after, portfolio_view
from stockbot.risk.rules import OrderIntent

PIN_TTL = timedelta(seconds=120)
LIQ_TTL = timedelta(seconds=120)

HELP = """명령어
/status 상태  /report 오늘 보고서  /positions 보유  /pending 승인 대기
/auto on|off 자동 모드 (on은 PIN)  /pause 일시정지  /stop 긴급 정지  /resume 재개 (PIN)
/mode paper|real 브로커 전환 (PIN)  /budget 금액 투입금 한도 (PIN)  /liquidate 전량 매도 (PIN)
/cost 이번 달 AI 비용  /ask 질문 (또는 그냥 질문을 보내세요)"""


@dataclass
class Reply:
    text: str
    buttons: list[tuple[str, str]] | None = None


# ------------------------------------------------------------- shared actions (web + telegram)
def check_pin(settings, pin: str | None) -> bool:
    return pin is not None and hmac.compare_digest(str(pin).strip(), str(settings.pin))


def set_automation(deps, value: str) -> None:
    cfg = deps.runtime()
    cfg.mode.automation = value
    deps.save_runtime(cfg)


def set_paused(deps, paused: bool, reason: str | None = None) -> None:
    cfg = deps.runtime()
    cfg.mode.paused, cfg.mode.pause_reason = paused, (reason if paused else None)
    deps.save_runtime(cfg)


def set_budget(deps, amount: float) -> None:
    cfg = deps.runtime()
    cfg.budget_usd = amount
    deps.save_runtime(cfg)


def set_broker_mode(deps, value: str) -> tuple[bool, str]:
    if value == "real" and getattr(deps, "real_broker", None) is None:
        return False, "실전 브로커가 아직 설정되지 않았습니다 (관리페이지에서 KIS 키 입력·연결 테스트 후 가능)."
    cfg = deps.runtime()
    cfg.mode.broker = value
    deps.save_runtime(cfg)
    return True, f"브로커를 {'실전' if value == 'real' else '모의'}로 전환했습니다."


def decide_approval(deps, approval_id: int, approve: bool, now: datetime) -> str:
    q = deps.approvals
    return q.approve(approval_id, now) if approve else q.reject(approval_id, now)


def last_session(now: datetime) -> date:
    d = now.astimezone(KST).date()
    for k in range(10):
        day = d - timedelta(days=k)
        if is_trading_day(day) and trading_session(day).close_kst <= now:
            return day
    return d


def liquidate(deps, now: datetime) -> str:
    intents = [OrderIntent(ticker=t, side="sell", qty=p.qty, kind="sell", reason="사용자 전량 매도",
                           idempotency_key=f"liquidate:{t}:{now.isoformat()}")
               for t, p in deps.broker.positions().items()]
    if not intents:
        return "보유 종목이 없습니다."
    if is_market_open(now):
        res = deps.executor.execute_now(intents, now)
        return "전량 매도 실행: " + ", ".join(f"{r.ticker} {r.status}" for r in res)
    cfg = deps.runtime()
    deps.executor.stage(intents, cfg.mode, cfg.rebuy_auto, next_open_after(now))
    return f"장이 닫혀 있어 다음 장 시작 때 {len(intents)}종목 전량 매도합니다."


def status_text(deps, now: datetime) -> str:
    cfg = deps.runtime()
    pf = portfolio_view(deps, PriceMarket(deps.prices, last_session(now)))
    m = cfg.mode
    lines = [f"모드: {'실전' if m.broker == 'real' else '모의'} · {'자동' if m.automation == 'auto' else '반자동'}"
             + (f" · ⛔ 정지 ({m.pause_reason})" if m.paused else ""),
             f"총자산 ${pf.equity:,.2f} (현금 ${pf.cash:,.2f}, 보유 {len(pf.positions)}종목)",
             f"투입금 한도 ${cfg.budget_usd:,.0f}",
             "허용 상품: " + (", ".join(n for n, on in (("ETF", cfg.active_rules().allow_etf),
                                                    ("레버리지·인버스", cfg.active_rules().allow_leveraged_etf),
                                                    ("저거래량", cfg.active_rules().allow_low_volume)) if on)
                            or "개별 주식만"),
             f"승인 대기 {len(deps.approvals.pending(now))}건",
             f"AI 비용 ${deps.budget.month_spend(now):.2f} / ${cfg.cost.monthly_cap_usd:.0f}"]
    failing = deps.health.failing()
    lines.append("상태: " + ("정상" if not failing else "장애 — " + ", ".join(failing)))
    return "\n".join(lines)


def positions_text(deps, now: datetime) -> str:
    pf = portfolio_view(deps, PriceMarket(deps.prices, last_session(now)))
    if not pf.positions:
        return "보유 종목이 없습니다."
    return "\n".join(f"{p.ticker}: {p.qty}주 평단 ${p.avg_price:,.2f} 현재 ${p.last_price:,.2f} ({p.pnl_pct:+.1%})"
                     for p in pf.positions.values())


def debate_text(deps, debate_id: int) -> str:
    with deps.session_factory() as s:
        r = s.get(DebateRow, debate_id)
        if r is None:
            return "토론 기록이 없습니다."
        res = r.result_json or {}
    lines = [f"토론 #{r.id} {r.ticker} ({r.as_of}) — 결론: {r.direction or ('교착' if r.deadlock else '없음')}"]
    for rnd in res.get("rounds", []):
        for o in rnd:
            lines.append(f"[R{o['round']}] {o['seat_id']}: {o['action']} ({o['confidence']:.2f}) {o['rationale'][:120]}")
    if r.referee_summary:
        lines.append(f"심판: {r.referee_summary}")
    return "\n".join(lines)


class CommandService:
    def __init__(self, deps, settings):
        self.d = deps
        self.settings = settings
        self._pin_wait: dict[int, tuple[str, str, datetime]] = {}
        self._liq_ok: dict[int, datetime] = {}

    def _allowed(self, chat_id: int) -> bool:
        return chat_id in set(self.settings.telegram_chat_ids)

    # ------------------------------------------------------------- text
    def handle_text(self, chat_id: int, text: str, now: datetime) -> Reply | None:
        if not self._allowed(chat_id):
            return None
        text = (text or "").strip()
        wait = self._pin_wait.pop(chat_id, None)
        if wait and now - wait[2] <= PIN_TTL and not text.startswith("/"):
            if not check_pin(self.settings, text):
                return Reply("PIN이 틀렸습니다. 요청을 취소했습니다.")
            return self._run_protected(chat_id, wait[0], wait[1], now)
        if not text.startswith("/"):
            return self._ask(text, now)
        cmd, _, arg = text.partition(" ")
        cmd, arg = cmd.lower().split("@")[0], arg.strip()
        if cmd in ("/start", "/help"):
            return Reply(HELP)
        if cmd == "/status":
            return Reply(status_text(self.d, now))
        if cmd == "/positions":
            return Reply(positions_text(self.d, now))
        if cmd == "/pending":
            return self._pending(now)
        if cmd == "/report":
            from stockbot.report.daily_report import collect_report_data, render_report

            return Reply(render_report(collect_report_data(self.d, last_session(now), now), None))
        if cmd == "/cost":
            cfg = self.d.runtime()
            return Reply(f"이번 달 AI 비용 ${self.d.budget.month_spend(now):.2f} / ${cfg.cost.monthly_cap_usd:.0f} "
                         f"({self.d.budget.state(now)})")
        if cmd == "/auto":
            if arg == "off":
                set_automation(self.d, "semi")
                return Reply("자동 모드를 껐습니다. 신규 매수는 승인을 받습니다.")
            if arg == "on":
                return self._ask_pin(chat_id, "auto_on", "", now)
            return Reply("사용법: /auto on 또는 /auto off")
        if cmd == "/pause":
            set_paused(self.d, True, "사용자 일시정지")
            return Reply("신규 매수를 일시정지했습니다. 손절·방어 매도는 계속 동작합니다.")
        if cmd == "/stop":
            set_paused(self.d, True, "사용자 긴급 정지")
            return Reply("⛔ 긴급 정지: 신규 주문을 모두 멈췄습니다. 보유 종목은 그대로입니다. 전량 매도는 /liquidate")
        if cmd == "/resume":
            return self._ask_pin(chat_id, "resume", "", now)
        if cmd == "/mode" and arg in ("paper", "real"):
            return self._ask_pin(chat_id, "mode", arg, now)
        if cmd == "/budget":
            try:
                amount = float(arg.replace(",", "").replace("$", ""))
                if amount <= 0:
                    raise ValueError
            except ValueError:
                return Reply("사용법: /budget 5000")
            return self._ask_pin(chat_id, "budget", str(amount), now)
        if cmd == "/liquidate":
            return self._ask_pin(chat_id, "liquidate", "", now)
        if cmd == "/ask":
            return self._ask(arg, now) if arg else Reply("사용법: /ask 질문")
        return Reply("알 수 없는 명령입니다.\n" + HELP)

    def _ask_pin(self, chat_id: int, action: str, arg: str, now: datetime) -> Reply:
        self._pin_wait[chat_id] = (action, arg, now)
        return Reply("PIN을 입력하세요 (2분 안에).")

    def _run_protected(self, chat_id: int, action: str, arg: str, now: datetime) -> Reply:
        if action == "auto_on":
            set_automation(self.d, "auto")
            return Reply("자동 모드를 켰습니다. 정해둔 한도 안에서 승인 없이 매수합니다.")
        if action == "resume":
            set_paused(self.d, False)
            return Reply("재개했습니다.")
        if action == "mode":
            return Reply(set_broker_mode(self.d, arg)[1])
        if action == "budget":
            set_budget(self.d, float(arg))
            return Reply(f"투입금 한도를 ${float(arg):,.0f}로 바꿨습니다.")
        if action == "liquidate":
            self._liq_ok[chat_id] = now
            return Reply("정말 전량 매도할까요?", buttons=[("예", "liquidate:yes"), ("아니오", "liquidate:no")])
        return Reply("알 수 없는 요청입니다.")

    def _pending(self, now: datetime) -> Reply:
        rows = self.d.approvals.pending(now)
        if not rows:
            return Reply("승인 대기 중인 주문이 없습니다.")
        lines, buttons = [], []
        for a in rows:
            lines.append(f"#{a.id} {a.ticker} {a.qty}주 {a.kind} — {a.reason}")
            buttons += [(f"승인 #{a.id}", f"approve:{a.id}"), (f"거절 #{a.id}", f"reject:{a.id}")]
        return Reply("\n".join(lines), buttons=buttons)

    def _ask(self, question: str, now: datetime) -> Reply:
        from stockbot.report.qa import answer_question, build_qa_context

        try:
            ctx = build_qa_context(self.d, last_session(now), now)
        except Exception:
            ctx = ""
        return Reply(answer_question(self.d.router, question, ctx, now))

    # ------------------------------------------------------------- buttons
    def handle_callback(self, chat_id: int, data: str, now: datetime) -> Reply | None:
        if not self._allowed(chat_id):
            return None
        kind, _, arg = (data or "").partition(":")
        if kind in ("approve", "reject") and arg.isdigit():
            res = decide_approval(self.d, int(arg), kind == "approve", now)
            return Reply({"ok": "승인했습니다" if kind == "approve" else "거절했습니다",
                          "already": "이미 처리된 건입니다", "expired": "만료된 건입니다"}[res])
        if kind == "detail" and arg.isdigit():
            with self.d.session_factory() as s:
                o = s.get(OrderRow, int(arg))
                if o is None:
                    return Reply("주문 기록이 없습니다.")
                from stockbot.models import DecisionRow

                dec = s.get(DecisionRow, o.decision_id) if o.decision_id else None
            return Reply(debate_text(self.d, dec.debate_id) if dec else f"{o.ticker} {o.qty}주 {o.kind}: {o.reason}")
        if kind == "debate" and arg.isdigit():
            return Reply(debate_text(self.d, int(arg)))
        if kind == "liquidate":
            ok_at = self._liq_ok.pop(chat_id, None)
            if arg != "yes":
                return Reply("전량 매도를 취소했습니다.")
            if ok_at is None or now - ok_at > LIQ_TTL:
                return Reply("PIN 확인이 필요합니다. /liquidate 부터 다시 해주세요.")
            return Reply(liquidate(self.d, now))
        return Reply("알 수 없는 버튼입니다.")
