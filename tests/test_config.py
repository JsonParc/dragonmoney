from pathlib import Path

from stockbot.config import RuntimeConfig, Settings
from stockbot.settings_store import load_runtime, save_runtime


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("STOCKBOT_WEB_PASSWORD", "pw")
    monkeypatch.setenv("STOCKBOT_PIN", "1234")
    monkeypatch.setenv("STOCKBOT_SECRET_KEY", "s")
    monkeypatch.setenv("STOCKBOT_TELEGRAM_CHAT_IDS", "[111,222]")
    s = Settings(_env_file=None)
    assert s.pin == "1234" and s.telegram_chat_ids == [111, 222]


def test_runtime_defaults():
    c = RuntimeConfig()
    assert c.risk.min_adv_usd == 50_000_000 and c.risk.max_adv_fraction == 0.01
    assert c.risk.max_position_pct == 0.20 and c.risk.max_holdings == 8
    assert c.risk.stop_loss_pct == -0.15 and c.risk.circuit_breaker_dd == -0.20
    assert c.debate.seats_per_team == 4 and c.debate.max_rebuttal_rounds == 2
    assert c.cost.monthly_cap_usd == 10.0 and c.mode.broker == "paper" and c.mode.automation == "semi"


def test_runtime_roundtrip(session_factory):
    with session_factory() as s:
        c = RuntimeConfig()
        c.mode.automation = "auto"
        save_runtime(s, c)
        s.commit()
    with session_factory() as s:
        assert load_runtime(s).mode.automation == "auto"


def test_env_file_is_gitignored():
    assert ".env" in Path(".gitignore").read_text().splitlines()
