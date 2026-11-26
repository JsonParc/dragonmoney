from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from fastapi.responses import JSONResponse

from stockbot.config import RuntimeConfig
from stockbot.state_file import export_state, import_state
from stockbot.telegram.commands import decide_approval, pin_guard, set_broker_mode
from stockbot.web import views
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
        return views.dashboard(deps, now_fn())

    @r.get("/debates", dependencies=[need])
    def debates(limit: int = 20):
        return views.debates(deps, limit)

    @r.get("/debates/{debate_id}", dependencies=[need])
    def debate(debate_id: int):
        d = views.debate_detail(deps, debate_id)
        if d is None:
            raise HTTPException(404, "토론 기록이 없습니다.")
        return d

    @r.get("/approvals", dependencies=[need])
    def approvals():
        return views.approvals(deps, now_fn())

    @r.post("/approvals/{approval_id}/{decision}", dependencies=[need])
    def decide(approval_id: int, decision: str):
        if decision not in ("approve", "reject"):
            raise HTTPException(404)
        return {"result": decide_approval(deps, approval_id, decision == "approve", now_fn())}

    @r.get("/scoreboard", dependencies=[need])
    def scoreboard():
        return views.scoreboard(deps)

    @r.get("/news", dependencies=[need])
    def news(min_severity: int = 0, hours: int = 72):
        return views.news(deps, now_fn(), min_severity, hours)

    @r.get("/health", dependencies=[need])
    def health():
        return deps.health.status()

    @r.get("/settings", dependencies=[need])
    def get_settings():
        return views.settings_view(deps)

    @r.get("/state/export", dependencies=[need])
    def state_export(with_cache: bool = False):
        now = now_fn()
        data = export_state(deps, now, include_cache=with_cache)
        name = f"dragonmoney-state-{now.strftime('%Y%m%d-%H%M')}.json"
        return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @r.post("/state/import", dependencies=[need])
    async def state_import(request: Request):
        body: dict[str, Any] = await request.json()
        res = pin_guard(deps).check(settings, body.get("pin"), now_fn())
        if res == "locked":
            raise HTTPException(429, "PIN을 여러 번 틀려 5분간 잠겼습니다.")
        if res != "ok":
            raise HTTPException(403, "학습 파일을 불러오려면 PIN이 필요합니다.")
        try:
            counts = import_state(deps, body.get("file") or {})
        except ValueError as e:
            raise HTTPException(422, str(e))
        return {"ok": True, "imported": counts}

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
