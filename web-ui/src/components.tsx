import { useEffect, useState, type ReactNode } from "react";
import { NavLink } from "react-router-dom";
import type { Mode, Opinion } from "./api";

export const SEAT_KO: Record<string, string> = {
  chart_trend: "추세", chart_volume: "세력", chart_candle: "캔들",
  news_news: "뉴스", news_case: "사례", news_macro: "거시",
};
export const ACTION_KO: Record<string, string> = {
  BUY: "신규 매수", ADD: "추가 매수", HOLD: "보유 유지", TRIM: "일부 매도", SELL: "매도",
  SELL_REBUY: "팔고 되사기", SWITCH: "종목 교체",
};
const LANE_OF: Record<string, 0 | 1 | 2> = { BUY: 0, ADD: 0, HOLD: 1, TRIM: 2, SELL: 2, SELL_REBUY: 2, SWITCH: 2 };
const DIR_LANE: Record<string, number> = { buy_side: 0, hold: 1, sell_side: 2 };

export const usd = (n: number) => `$${n.toLocaleString("en-US", { maximumFractionDigits: 2, minimumFractionDigits: 2 })}`;
export const pct = (n: number) => `${n >= 0 ? "+" : ""}${(n * 100).toFixed(1)}%`;

export function useLoad<T>(load: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    load().then((d) => alive && setData(d)).catch((e) => alive && setError(e.message));
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { data, error, reload: () => setTick((t) => t + 1) };
}

export function StatusStrip({ mode, failing }: { mode?: Mode; failing?: string[] }) {
  const bad = !!failing?.length || mode?.paused;
  return (
    <div className="strip">
      <span className={`dot ${bad ? "bad" : ""}`} aria-hidden />
      <span className="mode">
        {mode ? `${mode.broker === "real" ? "실전" : "모의"} · ${mode.automation === "auto" ? "자동" : "반자동"}` : "불러오는 중"}
      </span>
      <span className="spacer" />
      <span className="muted">{mode?.paused ? "정지됨" : failing?.length ? `장애: ${failing.join(", ")}` : "정상 작동"}</span>
    </div>
  );
}

export function Tabs({ pending }: { pending: number }) {
  const items = [["/", "홈"], ["/debates", "토론"], ["/approvals", "승인"], ["/news", "뉴스"], ["/settings", "설정"]];
  return (
    <div className="tabs">
      <nav>
        {items.map(([to, label]) => (
          <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => (isActive ? "active" : "")}>
            {label}
            {to === "/approvals" && pending > 0 && <span className="badge num">{pending}</span>}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

export function PinModal({ title, onSubmit, onClose }: { title: string; onSubmit: (pin: string) => Promise<void>; onClose: () => void }) {
  const [pin, setPin] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <div className="modal-back" role="dialog" aria-modal="true" aria-label={title} onClick={onClose}>
      <form className="modal" onClick={(e) => e.stopPropagation()} onSubmit={async (e) => {
        e.preventDefault(); setBusy(true); setErr(null);
        try { await onSubmit(pin); } catch (x) { setErr((x as Error).message); } finally { setBusy(false); }
      }}>
        <h2 style={{ marginTop: 0 }}>{title}</h2>
        <p className="muted">확인을 위해 PIN을 입력하세요.</p>
        <div className="field">
          <input autoFocus inputMode="numeric" type="password" value={pin} onChange={(e) => setPin(e.target.value)} aria-label="PIN" />
        </div>
        {err && <p className="error">{err}</p>}
        <div className="actions">
          <button type="button" className="btn" onClick={onClose}>취소</button>
          <button className="btn primary" disabled={!pin || busy}>확인</button>
        </div>
      </form>
    </div>
  );
}

export function Toast({ text }: { text: string | null }) {
  return text ? <div className="toast" role="status">{text}</div> : null;
}

export function Badge({ v }: { v: string }) {
  const ko: Record<string, string> = { confirmed: "확인됨", unconfirmed: "미확인", contradicted: "반박됨" };
  return <span className={`vb ${v}`}>{ko[v] ?? v}</span>;
}

/** The debate floor: each round is a band; seats sit in the lane of the side they voted for. */
export function DebateFloor({ rounds, direction, switched }: { rounds: Opinion[][]; direction: string | null; switched: string[] }) {
  const win = direction ? DIR_LANE[direction] : -1;
  const last = rounds.length - 1;
  return (
    <div>
      <div className="floor" role="table" aria-label="라운드별 좌석 입장">
        <div className="floor-head" role="row"><span>라운드</span><span>매수</span><span>유지</span><span>매도</span></div>
        {rounds.map((ops, ri) => {
          const lanes: ReactNode[][] = [[], [], []];
          ops.forEach((o) => {
            const moved = ri === last && ri > 0 && switched.includes(o.seat_id);
            lanes[LANE_OF[o.action] ?? 1].push(
              <span key={o.seat_id} className={`seat ${o.team} ${moved ? "moved" : ""} ${o.valid ? "" : "invalid"}`}
                title={`${SEAT_KO[o.seat_id] ?? o.seat_id}: ${ACTION_KO[o.action] ?? o.action}`}>
                {SEAT_KO[o.seat_id] ?? o.seat_id}
              </span>,
            );
          });
          return (
            <div className="floor-round" role="row" key={ri}>
              <span className="r">{ri === 0 ? "첫 의견" : `반박 ${ri}`}</span>
              {lanes.map((l, li) => <div key={li} className={`lane ${ri === last && li === win ? "win" : ""}`}>{l}</div>)}
            </div>
          );
        })}
      </div>
      <div className="legend"><span><i style={{ background: "var(--chart)" }} />차트팀</span><span><i style={{ background: "var(--news)" }} />뉴스팀</span><span>테두리 = 설득당해 옮김</span></div>
    </div>
  );
}

export function VoteBar({ shares }: { shares: Record<string, number> }) {
  const b = shares.buy_side ?? 0, h = shares.hold ?? 0, s = shares.sell_side ?? 0;
  return (
    <>
      <div className="votebar" aria-hidden><span style={{ width: `${b * 100}%` }} /><span style={{ width: `${h * 100}%` }} /><span style={{ width: `${s * 100}%` }} /></div>
      <div className="row sub" style={{ padding: 0 }}><span className="num">매수 {Math.round(b * 100)}%</span><span className="num">유지 {Math.round(h * 100)}%</span><span className="num">매도 {Math.round(s * 100)}%</span></div>
    </>
  );
}
