import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from pipe_fakes import NOW, SESSION, make_deps

from stockbot.pipeline.daily import DailyCycle
from stockbot.state_file import FORMAT, export_state, import_state
from stockbot.web.app import create_app

T = NOW + timedelta(hours=2)


@pytest.fixture
def trained():
    d = make_deps()
    DailyCycle(d).post_close(SESSION, NOW)
    cfg = d.runtime(); cfg.risk.stop_loss_pct = -0.11; cfg.rules_paper.allow_etf = True; d.save_runtime(cfg)
    d.scoreboard.record_debate(1, _deadlock(d), 100)  # changes seat weights
    return d


def _deadlock(d):
    from stockbot.debate.engine import DebateResult
    from stockbot.debate.schema import Direction, PersuasionRecord
    return DebateResult(ticker="X", as_of=SESSION, kind="regular", rounds=[[]], direction=None,
                        shares={x: 0.0 for x in Direction}, resolved=None, deadlock=True,
                        persuasion=PersuasionRecord(), invalid_seats=[], referee_summary="")


def test_export_has_state_and_views(trained):
    f = export_state(trained, T)
    assert f["format"] == FORMAT and f["version"] == 1 and f["exported_at"]
    assert {"runtime", "seat_scores", "debates", "opinions", "equity_snapshots", "paper_cash"} <= set(f["state"])
    v = f["views"]
    assert {"dashboard", "debates", "debate_details", "news", "scoreboard", "settings"} <= set(v)
    assert v["debates"] and str(v["debates"][0]["id"]) in v["debate_details"]
    json.dumps(f)  # must be plain JSON


def test_export_never_contains_secrets(trained):
    text = json.dumps(export_state(trained, T))
    assert "1234" not in text and '"pw"' not in text and "secret" not in text.lower().replace("secret_documents", "")


def test_cache_is_optional(trained):
    assert "llm_calls" not in export_state(trained, T)["state"]
    assert "llm_calls" in export_state(trained, T, include_cache=True)["state"]


def test_roundtrip_into_fresh_bot(trained):
    f = json.loads(json.dumps(export_state(trained, T)))
    fresh = make_deps()
    summary = import_state(fresh, f)
    assert summary["debates"] == len(f["state"]["debates"]) > 0
    assert fresh.runtime().risk.stop_loss_pct == -0.11 and fresh.runtime().rules_paper.allow_etf
    assert fresh.scoreboard.weights() == trained.scoreboard.weights()
    assert fresh.broker.cash() == pytest.approx(trained.broker.cash())


def test_import_rejects_foreign_files():
    with pytest.raises(ValueError):
        import_state(make_deps(), {"format": "something-else", "version": 1})


def test_web_export_and_pin_guarded_import(trained):
    c = TestClient(create_app(trained, trained.settings, now_fn=lambda: T))
    c.post("/api/login", json={"password": "pw"})
    f = c.get("/api/state/export").json()
    assert f["format"] == FORMAT
    assert c.post("/api/state/import", json={"file": f}).status_code == 403
    r = c.post("/api/state/import", json={"file": f, "pin": "1234"})
    assert r.status_code == 200 and r.json()["imported"]["debates"] > 0


def test_cli_export_import_and_demo(tmp_path):
    import subprocess
    import sys
    env = {"STOCKBOT_DB_URL": f"sqlite:///{(tmp_path / 't.db').as_posix()}", "STOCKBOT_WEB_PASSWORD": "pw",
           "STOCKBOT_PIN": "1234", "STOCKBOT_SECRET_KEY": "k", "SYSTEMROOT": r"C:\Windows", "PYTHONIOENCODING": "utf-8"}
    run = lambda *a: subprocess.run([sys.executable, "-m", "stockbot", *a], capture_output=True, env=env, cwd=tmp_path, timeout=180)
    demo = tmp_path / "demo.json"
    r = run("--export-demo", str(demo))
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    data = json.loads(demo.read_text(encoding="utf-8"))
    assert data["format"] == FORMAT and data["views"]["debates"]
    r = run("--import", str(demo))
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    out = tmp_path / "mine.json"
    assert run("--export", str(out)).returncode == 0
    assert json.loads(out.read_text(encoding="utf-8"))["state"]["debates"]
