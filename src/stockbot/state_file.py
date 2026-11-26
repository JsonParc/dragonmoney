"""Training file ("학습 파일"): move trained bot state between the PC and a server, and feed the static site.

{ "format": "dragonmoney-state", "version": 1, "exported_at": ISO,
  "state": { table rows used to restore a bot },
  "views": { pre-rendered API responses the static site shows read-only } }
No secrets (keys, PIN, password) are ever written.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, delete, inspect, select

from stockbot import models as m
from stockbot.config import RuntimeConfig
from stockbot.settings_store import load_runtime, save_runtime

FORMAT = "dragonmoney-state"
VERSION = 1
VIEW_DEBATES = 50

TABLES: dict[str, type] = {
    "seat_scores": m.SeatScore,
    "score_events": m.ScoreEvent,
    "decisions": m.DecisionRow,
    "debates": m.DebateRow,
    "opinions": m.OpinionRow,
    "equity_snapshots": m.EquitySnapshot,
    "paper_positions": m.PaperPosition,
    "paper_cash": m.PaperCash,
    "orders": m.OrderRow,
}
CACHE_TABLES: dict[str, type] = {"llm_calls": m.LLMCall}


def _dump_row(obj) -> dict:
    out = {}
    for col in inspect(obj).mapper.column_attrs:
        v = getattr(obj, col.key)
        out[col.key] = v.isoformat() if isinstance(v, (date, datetime)) else v
    return out


def _load_row(model, data: dict):
    cols = {c.key: c for c in inspect(model).mapper.column_attrs}
    kw = {}
    for k, v in data.items():
        if k not in cols:
            continue
        typ = cols[k].columns[0].type
        if v is not None and isinstance(typ, DateTime):
            v = datetime.fromisoformat(v).replace(tzinfo=None)
        elif v is not None and isinstance(typ, Date):
            v = date.fromisoformat(v)
        kw[k] = v
    return model(**kw)


def export_state(deps, now: datetime, include_cache: bool = False) -> dict[str, Any]:
    from stockbot.web import views

    state: dict[str, Any] = {"runtime": deps.runtime().model_dump(mode="json")}
    tables = {**TABLES, **(CACHE_TABLES if include_cache else {})}
    with deps.session_factory() as s:
        for name, model in tables.items():
            state[name] = [_dump_row(r) for r in s.execute(select(model)).scalars()]
    listing = views.debates(deps, VIEW_DEBATES)
    return {
        "format": FORMAT, "version": VERSION, "exported_at": now.isoformat(),
        "state": state,
        "views": {
            "dashboard": {**views.dashboard(deps, now), "pending_count": 0},
            "debates": listing,
            "debate_details": {str(d["id"]): views.debate_detail(deps, d["id"]) for d in listing},
            "news": views.news(deps, now),
            "scoreboard": views.scoreboard(deps),
            "settings": {**views.settings_view(deps), "seat_chains": {}},
            "approvals": [],
        },
    }


def import_state(deps, data: dict[str, Any]) -> dict[str, int]:
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("dragonmoney 학습 파일이 아닙니다.")
    if int(data.get("version", 0)) > VERSION:
        raise ValueError("더 새 버전에서 만든 학습 파일입니다. 봇을 업데이트하세요.")
    st = data.get("state") or {}
    counts: dict[str, int] = {}
    with deps.session_factory() as s:
        for name, model in {**TABLES, **CACHE_TABLES}.items():
            if name not in st:
                continue
            s.execute(delete(model))
            for row in st[name]:
                s.add(_load_row(model, row))
            counts[name] = len(st[name])
        if "runtime" in st:
            cur = load_runtime(s)
            new = RuntimeConfig.model_validate(st["runtime"])
            new.mode = cur.mode.model_copy(update={"paused": cur.mode.paused})  # never flip broker/auto via a file
            save_runtime(s, new)
        s.commit()
    return counts
