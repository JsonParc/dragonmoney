import { StrictMode, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { HashRouter, Route, Routes } from "react-router-dom";
import "./styles.css";
import { api, type Dashboard as Dash } from "./api";
import { StatusStrip, Tabs } from "./components";
import { detectMode, siteMode, snapshotInfo, useSnapshot } from "./site";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Debates from "./pages/Debates";
import DebateDetail from "./pages/DebateDetail";
import Approvals from "./pages/Approvals";
import News from "./pages/News";
import Settings from "./pages/Settings";

function StaticBanner({ onLoaded }: { onLoaded: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [err, setErr] = useState<string | null>(null);
  const info = snapshotInfo();
  return (
    <div className="static-banner" role="note">
      <div>
        <strong>정적 사이트</strong> — 학습 파일을 읽기만 합니다.
        {info ? ` ${new Date(info.exportedAt).toLocaleString("ko-KR")} 기준 (${info.source})` : " 아직 학습 파일이 없어요."}
      </div>
      <button className="btn" onClick={() => input.current?.click()}>학습 파일 열기</button>
      <input ref={input} type="file" accept=".json,application/json" hidden onChange={async (e) => {
        const f = e.target.files?.[0];
        if (!f) return;
        try { useSnapshot(JSON.parse(await f.text()), f.name); setErr(null); onLoaded(); }
        catch (x) { setErr((x as Error).message); }
        e.target.value = "";
      }} />
      {err && <p className="error" style={{ margin: 0 }}>{err}</p>}
    </div>
  );
}

function App() {
  const [ready, setReady] = useState(false);
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [dash, setDash] = useState<Dash | null>(null);
  const [version, setVersion] = useState(0);
  const refresh = () => api.get<Dash>("/dashboard").then((d) => { setDash(d); setAuthed(true); })
    .catch(() => setAuthed(siteMode() === "static"));

  useEffect(() => {
    detectMode().then(() => { setReady(true); refresh(); });
    const out = () => setAuthed(false);
    window.addEventListener("stockbot:logout", out);
    return () => window.removeEventListener("stockbot:logout", out);
  }, []);

  if (!ready || authed === null) return null;
  const isStatic = siteMode() === "static";
  if (!authed && !isStatic) return <Login onDone={refresh} />;
  return (
    <div className="shell" key={version}>
      {isStatic && <StaticBanner onLoaded={() => { setVersion((v) => v + 1); refresh(); }} />}
      <StatusStrip mode={dash?.mode} failing={dash?.failing} />
      <Routes>
        <Route path="/" element={dash ? <Dashboard dash={dash} refresh={refresh} /> : <p className="muted" style={{ marginTop: 24 }}>학습 파일을 열면 내용이 보여요.</p>} />
        <Route path="/debates" element={<Debates />} />
        <Route path="/debates/:id" element={<DebateDetail />} />
        <Route path="/approvals" element={<Approvals onChange={refresh} />} />
        <Route path="/news" element={<News />} />
        <Route path="/settings" element={<Settings onChange={refresh} />} />
      </Routes>
      <Tabs pending={dash?.pending_count ?? 0} />
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <HashRouter>
      <App />
    </HashRouter>
  </StrictMode>,
);
