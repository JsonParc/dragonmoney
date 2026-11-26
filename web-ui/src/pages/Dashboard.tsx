import { Link } from "react-router-dom";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Dashboard as Dash } from "../api";
import { pct, usd } from "../components";

export default function Dashboard({ dash }: { dash: Dash | null; refresh: () => void }) {
  if (!dash) return <p className="muted" style={{ marginTop: 24 }}>불러오는 중…</p>;
  const ret = dash.budget_usd ? dash.equity / dash.budget_usd - 1 : 0;
  const costRatio = dash.cost.cap ? dash.cost.spend / dash.cost.cap : 0;
  return (
    <>
      {(dash.pending_count > 0 || dash.mode.paused) && (
        <section className="panel decide" style={{ marginTop: 16 }}>
          {dash.mode.paused ? (
            <>
              <h2>신규 매수가 멈춰 있어요</h2>
              <p>{dash.mode.pause_reason ?? "사용자 정지"}</p>
              <Link to="/settings" className="btn">설정에서 재개하기</Link>
            </>
          ) : (
            <>
              <h2>승인을 기다리는 주문 {dash.pending_count}건</h2>
              <p className="muted">오늘 장 시작 전까지 승인하지 않으면 실행되지 않아요.</p>
              <Link to="/approvals" className="btn primary">승인하러 가기</Link>
            </>
          )}
        </section>
      )}

      <h1 className="equity num">{usd(dash.equity)}</h1>
      <p className="muted num">
        투입금 {usd(dash.budget_usd)} 대비 <span className={ret >= 0 ? "up" : "down"}>{pct(ret)}</span> · 현금 {usd(dash.cash)}
      </p>

      {dash.equity_curve.length > 1 && (
        <div className="panel" style={{ height: 200, padding: "12px 4px 4px" }}>
          <ResponsiveContainer>
            <LineChart data={dash.equity_curve}>
              <XAxis dataKey="date" hide />
              <YAxis domain={["auto", "auto"]} hide />
              <Tooltip formatter={(v: number) => usd(v)} labelFormatter={(l) => l} />
              <Line type="monotone" dataKey="equity" name="봇" stroke="var(--chart)" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="spy" name="SPY 보유 시" stroke="var(--muted)" strokeDasharray="4 3" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      <h2>보유 종목</h2>
      <div className="panel rows">
        {dash.positions.length === 0 && <p className="muted" style={{ margin: 0 }}>지금은 현금만 들고 있어요.</p>}
        {dash.positions.map((p) => (
          <div className="row" key={p.ticker}>
            <div><strong>{p.ticker}</strong><div className="sub num">{p.qty}주 · 평단 {usd(p.avg_price)}</div></div>
            <div style={{ textAlign: "right" }}>
              <div className="num">{usd(p.value)}</div>
              <div className={`sub num ${p.pnl_pct >= 0 ? "up" : "down"}`}>{pct(p.pnl_pct)}</div>
            </div>
          </div>
        ))}
      </div>

      <h2>봇 상태</h2>
      <div className="panel rows">
        <div className="row"><span>데이터·AI 연결</span><span className={dash.failing.length ? "down" : "up"}>{dash.failing.length ? `장애: ${dash.failing.join(", ")}` : "정상"}</span></div>
        <div className="row"><span>이번 달 AI 비용</span><span className={`num ${costRatio >= 0.8 ? "down" : ""}`}>{usd(dash.cost.spend)} / {usd(dash.cost.cap)}</span></div>
        <div className="row"><span>고점 대비</span><span className="num">{pct(dash.peak_equity ? dash.equity / dash.peak_equity - 1 : 0)}</span></div>
      </div>
    </>
  );
}
