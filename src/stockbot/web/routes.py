from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select

from stockbot.config import RuntimeConfig
from stockbot.models import DebateRow, EquitySnapshot
from stockbot.pipeline.context import PriceMarket, portfolio_view
from stockbot.telegram.commands import decide_approval, last_session, pin_guard, set_broker_mode
from stockbot.web.auth import COOKIE, MAX_AGE, Auth


class LoginBody(BaseModel):
    password: str


def _deep_merge(base: dict, patch: dict) -> dict:
    out = dict(base)
    for k, v in patch.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _is_safe_change(body: dict, cur: RuntimeConfig) -> bool:
    """Only changes that make the bot more conservative skip the PIN: pausing, turning auto off,
    paper-mode product options, and re-sending current values."""
    cur_d = cur.model_dump(mode="json")
    for k, v in body.items():
        if k == "rules_paper":
            continue
        if k == "mode" and isinstance(v, dict):
            for mk, mv in v.items():
                if (mk == "paused" and mv is True) or mk == "pause_reason" or (mk == "automation" and mv == "semi"):
                    continue
                if cur_d["mode"].get(mk) != mv:
                    return False
            continue
        if isinstance(v, dict) and isinstance(cur_d.get(k), dict):
            if any(cur_d[k].get(sk) != sv for sk, sv in v.items()):
                return False
        elif cur_d.get(k) != v:
            return False
    return True


def build_router(deps, settings, auth: Auth, now_fn: Callable[[], datetime]) -> APIRouter:
    r = APIRouter(prefix="/api")
    need = Depends(auth.require)

    @r.post("/login")
    def login(body: LoginBody, response: Response):
        token = auth.login(body.password)
        response.set_cookie(COOKIE, token, max_age=MAX_AGE, httponly=True, samesite="lax")
        return {"ok": True}

    @r.post("/logout")
    def logout(response: Response):
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @r.get("/dashboard", dependencies=[need])
    def dashboard():
        now = now_fn()
        cfg = deps.runtime()
        pf = portfolio_view(deps, PriceMarket(deps.prices, last_session(now)))
        with deps.session_factory() as s:
            snaps = s.execute(select(EquitySnapshot).order_by(EquitySnapshot.date)).scalars().all()
        base = next((x for x in snaps if x.spy_close), None)
        curve = [{"date": x.date.isoformat(), "equity": x.equity,
                  "spy": (x.spy_close / base.spy_close * snaps[0].equity) if (base and x.spy_close) else None}
                 for x in snaps]
        return {
            "equity": pf.equity, "cash": pf.cash, "peak_equity": pf.peak_equity, "budget_usd": cfg.budget_usd,
            "positions": [{**p.model_dump(), "pnl_pct": p.pnl_pct, "value": p.value} for p in pf.positions.values()],
            "mode": cfg.mode.model_dump(), "pending_count": len(deps.approvals.pending(now)),
            "health": deps.health.status(), "failing": deps.health.failing(),
            "cost": {"spend": deps.budget.month_spend(now), "cap": cfg.cost.monthly_cap_usd,
                     "state": deps.budget.state(now)},
            "equity_curve": curve,
        }

    @r.get("/debates", dependencies=[need])
    def debates(limit: int = 20):
        with deps.session_factory() as s:
            rows = s.execute(select(DebateRow).order_by(DebateRow.id.desc()).limit(min(limit, 200))).scalars().all()
        return [{"id": x.id, "ticker": x.ticker, "as_of": x.as_of.isoformat(), "kind": x.kind, "direction": x.direction,
                 "deadlock": x.deadlock, "persuading_team": x.persuading_team, "summary": x.referee_summary,
                 "action": ((x.result_json or {}).get("resolved") or {}).get("action")} for x in rows]

    @r.get("/debates/{debate_id}", dependencies=[need])
    def debate(debate_id: int):
        with deps.session_factory() as s:
            x = s.get(DebateRow, debate_id)
            if x is None:
                raise HTTPException(404, "토론 기록이 없습니다.")
            return {"id": x.id, **(x.result_json or {})}

    @r.get("/approvals", dependencies=[need])
    def approvals():
        return [a.model_dump(mode="json") for a in deps.approvals.pending(now_fn())]

    @r.post("/approvals/{approval_id}/{decision}", dependencies=[need])
    def decide(approval_id: int, decision: str):
        if decision not in ("approve", "reject"):
            raise HTTPException(404)
        return {"result": decide_approval(deps, approval_id, decision == "approve", now_fn())}

    @r.get("/scoreboard", dependencies=[need])
    def scoreboard():
        w = deps.scoreboard.weights()
        return {"seats": [{"seat_id": k, "weight": v} for k, v in w.items()], "summary": deps.scoreboard.summary_text()}

    @r.get("/news", dependencies=[need])
    def news(min_severity: int = 0, hours: int = 72):
        return [c.model_dump(mode="json") for c in deps.verifier.recent(now_fn(), hours) if c.severity >= min_severity]

    @r.get("/health", dependencies=[need])
    def health():
        return deps.health.status()

    @r.get("/settings", dependencies=[need])
    def get_settings():
        cfg = deps.runtime()
        st = deps.settings
        return {"runtime": cfg.model_dump(mode="json"),
                "keys": {"finnhub": bool(st.finnhub_key), "gemini": bool(st.gemini_key), "groq": bool(st.groq_key),
                         "openai": bool(st.openai_key), "anthropic": bool(st.anthropic_key),
                         "telegram": bool(st.telegram_token)},
                "real_broker_configured": getattr(deps, "real_broker", None) is not None,
                "seat_chains": {k: [c.provider + ":" + c.model for c in v]
                                for k, v in (deps.router.chains.items() if deps.router else [])}}

    @r.patch("/settings", dependencies=[need])
    async def patch_settings(request: Request):
        body: dict[str, Any] = await request.json()
        pin = body.pop("pin", None)
        cur = deps.runtime()
        mode = body.get("mode", {})
        if not _is_safe_change(body, cur):
            res = pin_guard(deps).check(settings, pin, now_fn())
            if res == "locked":
                raise HTTPException(429, "PIN을 여러 번 틀려 5분간 잠겼습니다.")
            if res != "ok":
                raise HTTPException(403, "이 변경에는 PIN이 필요합니다.")
        if mode.get("broker") and mode["broker"] != cur.mode.broker:
            ok, msg = set_broker_mode(deps, mode["broker"])
            if not ok:
                raise HTTPException(409, msg)
            cur = deps.runtime()
        merged = _deep_merge(cur.model_dump(mode="json"), body)
        if merged.get("mode", {}).get("paused") is False:
            merged["mode"]["pause_reason"] = None
        try:
            new = RuntimeConfig.model_validate(merged)
        except Exception as e:
            raise HTTPException(422, f"잘못된 설정값: {e}")
        deps.save_runtime(new)
        return {"ok": True, "runtime": new.model_dump(mode="json")}

    return r
