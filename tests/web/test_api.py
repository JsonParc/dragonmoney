from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from pipe_fakes import NOW, SESSION, make_deps

from stockbot.pipeline.daily import DailyCycle
from stockbot.web.app import create_app

T = NOW + timedelta(hours=2)


@pytest.fixture
def deps():
    d = make_deps()
    DailyCycle(d).post_close(SESSION, NOW)
    return d


@pytest.fixture
def client(deps):
    return TestClient(create_app(deps, deps.settings, static_dir=None, now_fn=lambda: T))


@pytest.fixture
def authed(client):
    assert client.post("/api/login", json={"password": "pw"}).status_code == 200
    return client


@pytest.fixture
def pending_approval_id(deps):
    return deps.approvals.pending(T)[0].id


def test_healthz_is_public(client):
    assert client.get("/healthz").json() == {"ok": True}


def test_requires_login(client):
    assert client.get("/api/dashboard").status_code == 401


def test_wrong_password(client):
    assert client.post("/api/login", json={"password": "x"}).status_code == 401


def test_login_then_dashboard(authed):
    body = authed.get("/api/dashboard").json()
    assert body["mode"]["broker"] == "paper" and "cost" in body and body["pending_count"] >= 1
    assert body["equity_curve"] and body["equity_curve"][-1]["date"] == SESSION.isoformat()


def test_lockout(client):
    for _ in range(5):
        client.post("/api/login", json={"password": "x"})
    assert client.post("/api/login", json={"password": "pw"}).status_code == 429


def test_logout(authed):
    authed.post("/api/logout")
    assert authed.get("/api/dashboard").status_code == 401


def test_debates_list_and_detail(authed):
    items = authed.get("/api/debates?limit=3").json()
    assert len(items) == 3
    detail = authed.get(f"/api/debates/{items[0]['id']}").json()
    assert detail["rounds"] and detail["ticker"] == items[0]["ticker"]
    assert authed.get("/api/debates/99999").status_code == 404


def test_auto_mode_needs_pin(authed, deps):
    assert authed.patch("/api/settings", json={"mode": {"automation": "auto"}}).status_code == 403
    assert authed.patch("/api/settings", json={"mode": {"automation": "auto"}, "pin": "1234"}).status_code == 200
    assert deps.runtime().mode.automation == "auto"


def test_risk_edit_needs_pin(authed, deps):
    assert authed.patch("/api/settings", json={"risk": {"stop_loss_pct": -0.1}}).status_code == 403
    assert authed.patch("/api/settings", json={"risk": {"stop_loss_pct": -0.1}, "pin": "1234"}).status_code == 200
    assert deps.runtime().risk.stop_loss_pct == -0.1


def test_real_mode_refused_without_broker(authed):
    r = authed.patch("/api/settings", json={"mode": {"broker": "real"}, "pin": "1234"})
    assert r.status_code == 409


def test_approve_endpoint(authed, pending_approval_id):
    assert authed.post(f"/api/approvals/{pending_approval_id}/approve").json()["result"] == "ok"
    assert authed.post(f"/api/approvals/{pending_approval_id}/approve").json()["result"] == "already"


def test_settings_hide_secrets(authed):
    body = authed.get("/api/settings").json()
    assert "pin" not in str(body).lower().replace("pin_required", "")
    assert body["keys"]["finnhub"] is False


def test_scoreboard_news_health(authed):
    assert len(authed.get("/api/scoreboard").json()["seats"]) == 6
    assert isinstance(authed.get("/api/news").json(), list)
    assert "prices" in authed.get("/api/health").json()


def test_real_rules_need_pin_paper_rules_do_not(authed, deps):
    assert authed.patch("/api/settings", json={"rules_paper": {"allow_etf": True}}).status_code == 200
    assert deps.runtime().rules_paper.allow_etf
    assert authed.patch("/api/settings", json={"rules_real": {"allow_leveraged_etf": True}}).status_code == 403
    assert authed.patch("/api/settings", json={"rules_real": {"allow_leveraged_etf": True}, "pin": "1234"}).status_code == 200
    assert deps.runtime().rules_real.allow_leveraged_etf
