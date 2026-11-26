import { api, type Cluster } from "../api";
import { Badge, useLoad } from "../components";

export default function News() {
  const { data, error } = useLoad(() => api.get<Cluster[]>("/news?hours=72"));
  const sorted = [...(data ?? [])].sort((a, b) => b.severity - a.severity || b.last_seen.localeCompare(a.last_seen));
  return (
    <>
      <h1>뉴스 감시</h1>
      <p className="muted">같은 사건을 여러 매체가 보도했는지 대조해요. 확인된 뉴스로만 긴급 토론을 엽니다.</p>
      {error && <p className="error">{error}</p>}
      <div className="panel rows">
        {sorted.length === 0 && <p className="muted" style={{ margin: 0 }}>최근 3일 동안 모은 뉴스가 없어요.</p>}
        {sorted.map((c) => (
          <div className="row" key={c.id} style={{ display: "block" }}>
            <div><Badge v={c.verification} /><span className="sev num">출처 {c.independent_sources}곳 · 심각도 {c.severity}</span></div>
            <div style={{ marginTop: 4 }}>{c.headline}</div>
            {c.tickers.length > 0 && <div className="sub">{c.tickers.join(", ")}</div>}
          </div>
        ))}
      </div>
    </>
  );
}
