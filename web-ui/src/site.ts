/** Site mode: "live" when a bot server answers /healthz, otherwise "static" (read-only view of a training file). */
export type SiteMode = "live" | "static";

export type StateFile = {
  format: string;
  label?: string;
  version: number;
  exported_at: string;
  views: {
    dashboard: unknown; debates: { id: number }[]; debate_details: Record<string, unknown>;
    news: unknown[]; scoreboard: unknown; settings: unknown; approvals: unknown[];
  };
};

export const STATE_FORMAT = "dragonmoney-state";
let mode: SiteMode = "live";
let snapshot: StateFile | null = null;
let source = "";

export const siteMode = () => mode;
export const snapshotInfo = () => (snapshot ? { exportedAt: snapshot.exported_at, source } : null);

export async function detectMode(): Promise<SiteMode> {
  try {
    const r = await fetch("/healthz", { cache: "no-store" });
    const j = await r.json();
    if (j && j.ok === true) return (mode = "live");
  } catch {
    /* no server: static hosting */
  }
  mode = "static";
  try {
    const r = await fetch("./stockbot-state.json", { cache: "no-store" });
    if (r.ok) useSnapshot(await r.json(), "사이트에 올린 학습 파일");
  } catch {
    snapshot = null;
  }
  return mode;
}

export function useSnapshot(data: unknown, label: string): void {
  const f = data as StateFile;
  if (!f || f.format !== STATE_FORMAT || !f.views) throw new Error("dragonmoney 학습 파일이 아닙니다.");
  snapshot = f;
  source = f.label ? `${f.label}, ${label}` : label;
}

const READ_ONLY = "정적 사이트에서는 바꿀 수 없어요. 서버(동적 사이트)에서 실행할 때만 가능합니다.";

export function staticCall(method: string, path: string): unknown {
  if (path === "/login" || path === "/logout") return { ok: true };
  if (!snapshot) throw Object.assign(new Error("학습 파일이 없습니다. '학습 파일 열기'로 파일을 골라주세요."), { status: 404 });
  if (method !== "GET") throw Object.assign(new Error(READ_ONLY), { status: 405 });
  const v = snapshot.views;
  const [base] = path.split("?");
  if (base === "/dashboard") return v.dashboard;
  if (base.startsWith("/debates/")) {
    const d = v.debate_details[base.split("/")[2]];
    if (!d) throw Object.assign(new Error("이 학습 파일에 없는 토론입니다."), { status: 404 });
    return d;
  }
  if (base === "/debates") return v.debates;
  if (base === "/approvals") return [];
  if (base === "/news") return v.news;
  if (base === "/scoreboard") return v.scoreboard;
  if (base === "/settings") return v.settings;
  if (base === "/state/export") return snapshot;
  throw Object.assign(new Error("정적 사이트에서 쓸 수 없는 기능입니다."), { status: 404 });
}
