"""Read-only view payloads shared by the live web API and the exported training file (static site)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from stockbot.models import DebateRow, EquitySnapshot
from stockbot.pipeline.context import PriceMarket, portfolio_view
from stockbot.telegram.commands import last_session


def dashboard(deps, now: datetime) -> dict:
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
        "health": {k: {**v, "at": v["at"].isoformat() if v.get("at") else None} for k, v in deps.health.status().items()},
        "failing": deps.health.failing(),
        "cost": {"spend": deps.budget.month_spend(now), "cap": cfg.cost.monthly_cap_usd, "state": deps.budget.state(now)},
        "equity_curve": curve,
    }


def debates(deps, limit: int = 20) -> list[dict]:
    with deps.session_factory() as s:
        rows = s.execute(select(DebateRow).order_by(DebateRow.id.desc()).limit(min(limit, 200))).scalars().all()
    return [{"id": x.id, "ticker": x.ticker, "as_of": x.as_of.isoformat(), "kind": x.kind, "direction": x.direction,
             "deadlock": x.deadlock, "persuading_team": x.persuading_team, "summary": x.referee_summary,
             "action": ((x.result_json or {}).get("resolved") or {}).get("action")} for x in rows]


def debate_detail(deps, debate_id: int) -> dict | None:
    with deps.session_factory() as s:
        x = s.get(DebateRow, debate_id)
        return {"id": x.id, **(x.result_json or {})} if x else None


def approvals(deps, now: datetime) -> list[dict]:
    return [a.model_dump(mode="json") for a in deps.approvals.pending(now)]


def scoreboard(deps) -> dict:
    w = deps.scoreboard.weights()
    return {"seats": [{"seat_id": k, "weight": v} for k, v in w.items()], "summary": deps.scoreboard.summary_text()}


def news(deps, now: datetime, min_severity: int = 0, hours: int = 72) -> list[dict]:
    return [c.model_dump(mode="json") for c in deps.verifier.recent(now, hours) if c.severity >= min_severity]


def settings_view(deps) -> dict:
    cfg = deps.runtime()
    st = deps.settings
    return {"runtime": cfg.model_dump(mode="json"),
            "keys": {"finnhub": bool(st.finnhub_key), "gemini": bool(st.gemini_key), "groq": bool(st.groq_key),
                     "openai": bool(st.openai_key), "anthropic": bool(st.anthropic_key),
                     "telegram": bool(st.telegram_token)},
            "real_broker_configured": getattr(deps, "real_broker", None) is not None,
            "seat_chains": {k: [c.provider + ":" + c.model for c in v]
                            for k, v in (deps.router.chains.items() if deps.router else [])}}
