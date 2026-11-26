import { useState } from "react";
import { api } from "../api";

export default function Login({ onDone }: { onDone: () => void }) {
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null);
  return (
    <div className="login">
      <form onSubmit={async (e) => {
        e.preventDefault(); setErr(null);
        try { await api.post("/login", { password: pw }); onDone(); } catch (x) { setErr((x as Error).message); }
      }}>
        <h1>주식 봇 관리</h1>
        <p className="muted">관리 비밀번호로 로그인하세요.</p>
        <div className="field">
          <label htmlFor="pw">비밀번호</label>
          <input id="pw" type="password" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} />
        </div>
        {err && <p className="error">{err}</p>}
        <button className="btn primary" style={{ width: "100%" }} disabled={!pw}>로그인</button>
      </form>
    </div>
  );
}
