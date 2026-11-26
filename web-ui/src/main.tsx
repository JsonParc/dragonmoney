import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import "./styles.css";
import { api, type Dashboard as Dash } from "./api";
import { StatusStrip, Tabs } from "./components";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Debates from "./pages/Debates";
import DebateDetail from "./pages/DebateDetail";
import Approvals from "./pages/Approvals";
import News from "./pages/News";
import Settings from "./pages/Settings";

function App() {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [dash, setDash] = useState<Dash | null>(null);
  const refresh = () => api.get<Dash>("/dashboard").then((d) => { setDash(d); setAuthed(true); }).catch(() => setAuthed(false));

  useEffect(() => {
    refresh();
    const out = () => setAuthed(false);
    window.addEventListener("stockbot:logout", out);
    return () => window.removeEventListener("stockbot:logout", out);
  }, []);

  if (authed === null) return null;
  if (!authed) return <Login onDone={refresh} />;
  return (
    <div className="shell">
      <StatusStrip mode={dash?.mode} failing={dash?.failing} />
      <Routes>
        <Route path="/" element={<Dashboard dash={dash} refresh={refresh} />} />
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
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
