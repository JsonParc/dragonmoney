import { useEffect, useState } from "react";
import { api } from "../api";
import { PinModal, Toast, useLoad } from "../components";

type Runtime = {
  mode: { broker: string; automation: string; paused: boolean; pause_reason: string | null };
  budget_usd: number; rebuy_auto: boolean; severity_threshold: number;
  risk: Record<string, number>; cost: { monthly_cap_usd: number };
  rules_paper: Rules; rules_real: Rules;
};
type Rules = { allow_etf: boolean; allow_leveraged_etf: boolean; allow_low_volume: boolean };
const RULES: [keyof Rules, string, string][] = [
  ["allow_etf", "ETF 매수", "SPY·QQQ·섹터·채권·금 ETF"],
  ["allow_leveraged_etf", "레버리지·인버스 ETF", "SOXL·TQQQ·SQQQ 등. 오래 들면 감쇠 위험"],
  ["allow_low_volume", "거래량 적은 종목", "거래대금 하한 해제 (주문량 1% 규칙은 유지)"],
];
type SettingsResp = { runtime: Runtime; keys: Record<string, boolean>; real_broker_configured: boolean; seat_chains: Record<string, string[]> };

const RISK_FIELDS: [string, string, number][] = [
  ["stop_loss_pct", "강제 손절선 (예: -0.15 = -15%)", 0.01],
  ["max_position_pct", "종목당 최대 비중 (0.2 = 20%)", 0.01],
  ["max_holdings", "최대 보유 종목 수", 1],
  ["min_adv_usd", "최소 하루 평균 거래대금 ($)", 1_000_000],
  ["max_daily_notional_pct", "하루 매수 한도 (투입금 대비)", 0.01],
  ["circuit_breaker_dd", "자동 정지 손실 (고점 대비)", 0.01],
];
const KEY_KO: Record<string, string> = { finnhub: "Finnhub (시세·뉴스)", gemini: "Gemini", groq: "Groq", openai: "OpenAI", anthropic: "Claude", telegram: "텔레그램 봇" };

export default function Settings({ onChange }: { onChange: () => void }) {
  const { data, reload } = useLoad(() => api.get<SettingsResp>("/settings"));
  const [risk, setRisk] = useState<Record<string, number>>({});
  const [budget, setBudget] = useState("");
  const [pinFor, setPinFor] = useState<{ title: string; patch: object } | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => { if (data) { setRisk(data.runtime.risk); setBudget(String(data.runtime.budget_usd)); } }, [data]);
  if (!data) return <p className="muted" style={{ marginTop: 24 }}>불러오는 중…</p>;
  const rt = data.runtime;

  const flash = (t: string) => { setToast(t); setTimeout(() => setToast(null), 2500); };
  const save = async (patch: object, msg: string) => {
    await api.patch("/settings", patch); flash(msg); reload(); onChange();
  };
  const withPin = (title: string, patch: object) => setPinFor({ title, patch });

  return (
    <>
      <h1>설정</h1>

      <h2>매매 모드</h2>
      <div className="panel rows">
        <label className="switch">
          <span>자동 모드<div className="sub muted">켜면 승인 없이 한도 안에서 매수해요.</div></span>
          <input type="checkbox" checked={rt.mode.automation === "auto"} onChange={(e) =>
            e.target.checked ? withPin("자동 모드 켜기", { mode: { automation: "auto" } })
              : save({ mode: { automation: "semi" } }, "자동 모드를 껐어요")} />
        </label>
        <label className="switch">
          <span>신규 매수 정지<div className="sub muted">{rt.mode.paused ? rt.mode.pause_reason ?? "정지됨" : "손절·방어 매도는 계속 동작해요."}</div></span>
          <input type="checkbox" checked={rt.mode.paused} onChange={(e) =>
            e.target.checked ? save({ mode: { paused: true, pause_reason: "웹에서 정지" } }, "신규 매수를 멈췄어요")
              : withPin("매수 재개", { mode: { paused: false } })} />
        </label>
        <div className="switch">
          <span>브로커<div className="sub muted">{rt.mode.broker === "real" ? "실전 계좌" : "모의투자"}{!data.real_broker_configured && " · 실전 계좌 미연결"}</div></span>
          <button className="btn" disabled={!data.real_broker_configured && rt.mode.broker === "paper"}
            onClick={() => withPin(rt.mode.broker === "real" ? "모의로 전환" : "실전으로 전환", { mode: { broker: rt.mode.broker === "real" ? "paper" : "real" } })}>
            {rt.mode.broker === "real" ? "모의로 전환" : "실전으로 전환"}
          </button>
        </div>
      </div>

      <h2>매수 허용 상품</h2>
      <div className="panel">
        <div className="row sub" style={{ paddingTop: 0 }}><span /><span style={{ display: "flex", gap: 22 }}><span>모의</span><span>실전</span></span></div>
        {RULES.map(([k, label, hint]) => (
          <div className="row" key={k}>
            <span>{label}<div className="sub muted">{hint}</div></span>
            <span style={{ display: "flex", gap: 22 }}>
              <input type="checkbox" aria-label={`모의 ${label}`} style={{ width: 22, height: 22, accentColor: "var(--chart)" }}
                checked={rt.rules_paper[k]} onChange={(e) => save({ rules_paper: { [k]: e.target.checked } }, `모의투자: ${label} ${e.target.checked ? "허용" : "금지"}`)} />
              <input type="checkbox" aria-label={`실전 ${label}`} style={{ width: 22, height: 22, accentColor: "var(--news)" }}
                checked={rt.rules_real[k]} onChange={(e) => withPin(`실전: ${label} ${e.target.checked ? "허용" : "금지"}`, { rules_real: { [k]: e.target.checked } })} />
            </span>
          </div>
        ))}
        <p className="sub muted" style={{ margin: "8px 0 0" }}>실전 옵션을 바꿀 때는 PIN이 필요해요. 지금 모드에 맞는 쪽이 적용됩니다.</p>
      </div>

      <h2>투입금 한도</h2>
      <div className="panel">
        <div className="field">
          <label htmlFor="budget">봇이 굴릴 수 있는 최대 금액 ($)</label>
          <input id="budget" inputMode="decimal" value={budget} onChange={(e) => setBudget(e.target.value)} />
        </div>
        <button className="btn primary" disabled={Number(budget) === rt.budget_usd || !(Number(budget) > 0)}
          onClick={() => withPin("투입금 한도 변경", { budget_usd: Number(budget) })}>투입금 저장</button>
      </div>

      <h2>리스크 규칙</h2>
      <div className="panel">
        {RISK_FIELDS.map(([k, label, step]) => (
          <div className="field" key={k}>
            <label htmlFor={k}>{label}</label>
            <input id={k} type="number" step={step} value={risk[k] ?? ""} onChange={(e) => setRisk({ ...risk, [k]: Number(e.target.value) })} />
          </div>
        ))}
        <button className="btn primary" onClick={() => withPin("리스크 규칙 저장", { risk })}>리스크 규칙 저장</button>
      </div>

      <h2>연결 상태</h2>
      <div className="panel rows">
        {Object.entries(data.keys).map(([k, ok]) => (
          <div className="row" key={k}><span>{KEY_KO[k] ?? k}</span><span className={ok ? "up" : "muted"}>{ok ? "연결됨" : "키 없음"}</span></div>
        ))}
      </div>

      <h2>토론 좌석과 AI 모델</h2>
      <div className="panel rows">
        {Object.entries(data.seat_chains).map(([seat, chain]) => (
          <div className="row" key={seat}><span>{seat}</span><span className="sub">{chain[0] ?? "모델 없음"}{chain.length > 1 && ` 외 ${chain.length - 1}`}</span></div>
        ))}
      </div>

      <div style={{ marginTop: 24 }}>
        <button className="btn" onClick={async () => { await api.post("/logout"); window.dispatchEvent(new Event("stockbot:logout")); }}>로그아웃</button>
      </div>

      {pinFor && <PinModal title={pinFor.title} onClose={() => setPinFor(null)} onSubmit={async (pin) => {
        await save({ ...pinFor.patch, pin }, `${pinFor.title} 완료`); setPinFor(null);
      }} />}
      <Toast text={toast} />
    </>
  );
}
