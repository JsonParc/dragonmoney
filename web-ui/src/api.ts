import { siteMode, staticCall } from "./site";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  if (siteMode() === "static") {
    try {
      return staticCall(method, path) as T;
    } catch (e) {
      const err = e as Error & { status?: number };
      throw new ApiError(err.status ?? 400, err.message);
    }
  }
  const res = await fetch(`/api${path}`, {
    method,
    credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401 && path !== "/login") {
    window.dispatchEvent(new Event("stockbot:logout"));
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, (data as { detail?: string }).detail ?? `오류 ${res.status}`);
  return data as T;
}

export const api = {
  get: <T,>(p: string) => call<T>("GET", p),
  post: <T,>(p: string, b?: unknown) => call<T>("POST", p, b),
  patch: <T,>(p: string, b: unknown) => call<T>("PATCH", p, b),
};

export type Mode = { broker: "paper" | "real"; automation: "semi" | "auto"; paused: boolean; pause_reason: string | null };
export type Position = { ticker: string; qty: number; avg_price: number; last_price: number; pnl_pct: number; value: number };
export type Dashboard = {
  equity: number; cash: number; peak_equity: number; budget_usd: number; positions: Position[]; mode: Mode;
  pending_count: number; failing: string[]; cost: { spend: number; cap: number; state: string };
  equity_curve: { date: string; equity: number; spy: number | null }[];
};
export type DebateItem = {
  id: number; ticker: string; as_of: string; kind: string; direction: string | null; deadlock: boolean;
  persuading_team: string | null; summary: string; action: string | null;
};
export type Opinion = {
  seat_id: string; team: "chart" | "news"; round: number; action: string; confidence: number; rationale: string;
  valid: boolean; rebuy_price?: number | null; expected_drop_pct?: number | null;
};
export type DebateDetail = {
  id: number; ticker: string; as_of: string; kind: string; rounds: Opinion[][]; direction: string | null;
  shares: Record<string, number>; deadlock: boolean; referee_summary: string;
  persuasion: { persuading_team: string | null; switched_seats: string[] };
  resolved: { action: string; rebuy_price?: number | null; switch_to?: string | null } | null;
};
export type Approval = { id: number; ticker: string; side: string; qty: number; kind: string; reason: string; expires_at: string };
export type Cluster = {
  id: number; headline: string; tickers: string[]; tags: string[]; verification: "confirmed" | "unconfirmed" | "contradicted";
  independent_sources: number; severity: number; last_seen: string;
};
