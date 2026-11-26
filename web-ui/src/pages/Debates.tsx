import { Link } from "react-router-dom";
import { api, type DebateItem } from "../api";
import { ACTION_KO, useLoad } from "../components";

export default function Debates() {
  const { data, error } = useLoad(() => api.get<DebateItem[]>("/debates?limit=50"));
  return (
    <>
      <h1>토론 기록</h1>
      <p className="muted">차트팀과 뉴스팀이 종목마다 토론한 결과예요.</p>
      {error && <p className="error">{error}</p>}
      <div className="panel rows">
        {data?.length === 0 && <p className="muted" style={{ margin: 0 }}>아직 토론이 없어요. 장 마감 후 첫 토론이 열립니다.</p>}
        {data?.map((d) => (
          <Link to={`/debates/${d.id}`} key={d.id} className="row" style={{ textDecoration: "none" }}>
            <div>
              <strong>{d.ticker}</strong> {d.kind === "emergency" && <span className="vb contradicted" style={{ textDecoration: "none" }}>긴급</span>}
              <div className="sub">{d.as_of}{d.persuading_team && ` · ${d.persuading_team === "chart" ? "차트팀" : "뉴스팀"}이 설득`}</div>
            </div>
            <span>{d.deadlock ? "교착" : d.action ? ACTION_KO[d.action] ?? d.action : "결정 없음"}</span>
          </Link>
        ))}
      </div>
    </>
  );
}
