import { useState } from "react";
import { api, type Approval } from "../api";
import { Toast, useLoad } from "../components";

const KIND_KO: Record<string, string> = { new_buy: "신규 매수", add: "추가 매수", switch_buy: "교체 매수", rebuy: "되사기" };
const RESULT_KO: Record<string, string> = { ok: "처리했어요", already: "이미 처리된 주문이에요", expired: "시간이 지나 만료됐어요" };

export default function Approvals({ onChange }: { onChange: () => void }) {
  const { data, error, reload } = useLoad(() => api.get<Approval[]>("/approvals"));
  const [toast, setToast] = useState<string | null>(null);
  const decide = async (a: Approval, d: "approve" | "reject") => {
    const r = await api.post<{ result: string }>(`/approvals/${a.id}/${d}`);
    setToast(r.result === "ok" ? (d === "approve" ? `${a.ticker} 승인했어요` : `${a.ticker} 거절했어요`) : RESULT_KO[r.result]);
    setTimeout(() => setToast(null), 2500);
    reload(); onChange();
  };
  return (
    <>
      <h1>승인 대기</h1>
      <p className="muted">반자동 모드에서는 매수만 승인을 받아요. 매도·손절은 바로 실행됩니다.</p>
      {error && <p className="error">{error}</p>}
      {data?.length === 0 && <div className="panel"><p className="muted" style={{ margin: 0 }}>승인할 주문이 없어요.</p></div>}
      {data?.map((a) => (
        <section className="panel decide" key={a.id} style={{ marginBottom: 12 }}>
          <h2 className="num">{a.ticker} {a.qty}주 {KIND_KO[a.kind] ?? a.kind}</h2>
          <p className="muted">{a.reason}</p>
          <p className="sub muted">마감: {new Date(a.expires_at).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" })}</p>
          <div className="actions">
            <button className="btn" onClick={() => decide(a, "reject")}>거절</button>
            <button className="btn primary" onClick={() => decide(a, "approve")}>승인</button>
          </div>
        </section>
      ))}
      <Toast text={toast} />
    </>
  );
}
