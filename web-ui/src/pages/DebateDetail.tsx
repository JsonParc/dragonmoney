import { useParams } from "react-router-dom";
import { api, type DebateDetail as Detail } from "../api";
import { ACTION_KO, DebateFloor, SEAT_KO, VoteBar, useLoad } from "../components";

export default function DebateDetail() {
  const { id } = useParams();
  const { data: d, error } = useLoad(() => api.get<Detail>(`/debates/${id}`), [id]);
  if (error) return <p className="error" style={{ marginTop: 24 }}>{error}</p>;
  if (!d) return <p className="muted" style={{ marginTop: 24 }}>불러오는 중…</p>;
  const final = d.rounds[d.rounds.length - 1] ?? [];
  const verdict = d.deadlock ? "교착 — 거래하지 않음" : d.resolved ? ACTION_KO[d.resolved.action] ?? d.resolved.action : "결정 없음";
  return (
    <>
      <h1>{d.ticker} {d.kind === "emergency" ? "긴급 토론" : "토론"}</h1>
      <p className="muted">{d.as_of} · 결론: <strong style={{ color: "var(--ink)" }}>{verdict}</strong>
        {d.resolved?.rebuy_price ? ` (되살 가격 $${d.resolved.rebuy_price})` : ""}
        {d.resolved?.switch_to ? ` → ${d.resolved.switch_to}` : ""}</p>

      <section className="panel" style={{ marginTop: 12 }}>
        <DebateFloor rounds={d.rounds} direction={d.direction} switched={d.persuasion.switched_seats} />
        <VoteBar shares={d.shares} />
        {d.persuasion.persuading_team && (
          <p style={{ marginTop: 10 }}>
            {d.persuasion.persuading_team === "chart" ? "차트팀" : "뉴스팀"}이 {d.persuasion.switched_seats.map((s) => SEAT_KO[s] ?? s).join(", ")}을(를) 설득했어요.
            결과가 맞으면 보너스, 틀리면 감점됩니다.
          </p>
        )}
      </section>

      {d.referee_summary && (<><h2>심판 요약</h2><div className="panel"><p style={{ margin: 0 }}>{d.referee_summary}</p></div></>)}

      <h2>최종 발언</h2>
      <div className="panel rows">
        {final.map((o) => (
          <div className="opinion" key={o.seat_id}>
            <div className={`who ${o.team}`}>{SEAT_KO[o.seat_id] ?? o.seat_id} · {ACTION_KO[o.action] ?? o.action} <span className="muted num">확신 {Math.round(o.confidence * 100)}%</span></div>
            <p>{o.valid ? o.rationale : "응답 실패로 기권 처리됐어요."}</p>
          </div>
        ))}
      </div>
    </>
  );
}
