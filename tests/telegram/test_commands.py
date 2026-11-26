from datetime import timedelta

import httpx
import pytest
from llm_fakes import ScriptedClient
from pipe_fakes import NOW, SESSION, hold, make_deps

from stockbot.llm.router import LLMRouter
from stockbot.pipeline.daily import DailyCycle
from stockbot.telegram.bot import TelegramNotifier, TelegramPoller
from stockbot.telegram.commands import CommandService

T = NOW + timedelta(hours=2)


class _Free:
    def allow(self, c, now): return True
    def record(self, r, now): pass


@pytest.fixture
def deps():
    return make_deps()


@pytest.fixture
def svc(deps):
    return CommandService(deps, deps.settings)


def mode(deps):
    return deps.runtime().mode


@pytest.fixture
def pending_approval_id(deps):
    DailyCycle(deps).post_close(SESSION, NOW)
    return deps.approvals.pending(T)[0].id


@pytest.fixture
def expired_approval_id(deps):
    return deps.approvals.create(order_id=999, expires_at=NOW)


def test_unknown_chat_ignored(svc):
    assert svc.handle_text(999, "/status", T) is None
    assert svc.handle_callback(999, "approve:1", T) is None


def test_status(svc):
    text = svc.handle_text(111, "/status", T).text
    assert "모의" in text and "반자동" in text


def test_auto_on_requires_pin(svc, deps):
    assert "PIN" in svc.handle_text(111, "/auto on", T).text
    assert svc.handle_text(111, "0000", T).text.startswith("PIN이 틀렸")
    assert mode(deps).automation == "semi"
    svc.handle_text(111, "/auto on", T)
    svc.handle_text(111, "1234", T)
    assert mode(deps).automation == "auto"
    svc.handle_text(111, "/auto off", T)
    assert mode(deps).automation == "semi"


def test_pin_prompt_expires(svc, deps):
    svc.handle_text(111, "/auto on", T)
    svc.handle_text(111, "1234", T + timedelta(seconds=121))
    assert mode(deps).automation == "semi"


def test_stop_without_pin_and_resume_with_pin(svc, deps):
    svc.handle_text(111, "/stop", T)
    assert mode(deps).paused
    svc.handle_text(111, "/resume", T)
    svc.handle_text(111, "1234", T)
    assert not mode(deps).paused


def test_budget_change(svc, deps):
    svc.handle_text(111, "/budget 5000", T)
    svc.handle_text(111, "1234", T)
    assert deps.runtime().budget_usd == 5000


def test_double_approve(svc, pending_approval_id):
    assert svc.handle_callback(111, f"approve:{pending_approval_id}", T).text == "승인했습니다"
    assert svc.handle_callback(111, f"approve:{pending_approval_id}", T).text == "이미 처리된 건입니다"


def test_approve_after_expiry(svc, expired_approval_id):
    assert svc.handle_callback(111, f"approve:{expired_approval_id}", T).text == "만료된 건입니다"


def test_pending_lists_approvals(svc, pending_approval_id):
    r = svc.handle_text(111, "/pending", T)
    assert f"#{pending_approval_id}" in r.text and r.buttons


def test_mode_real_without_broker(svc):
    svc.handle_text(111, "/mode real", T)
    assert "설정되지 않았습니다" in svc.handle_text(111, "1234", T).text


def test_liquidate_needs_pin_and_confirm(svc, deps):
    hold(deps, "UP3", qty=3)
    svc.handle_text(111, "/liquidate", T)
    r = svc.handle_text(111, "1234", T)
    assert ("예", "liquidate:yes") in r.buttons
    assert svc.handle_callback(222, "liquidate:yes", T) is None
    svc.handle_callback(111, "liquidate:yes", T)
    from stockbot.models import OrderRow
    with deps.session_factory() as s:
        assert s.query(OrderRow).filter_by(ticker="UP3", side="sell").count() == 1


def test_liquidate_yes_without_pin_is_refused(svc):
    assert "PIN" in svc.handle_callback(111, "liquidate:yes", T).text


def test_free_text_is_question(deps):
    deps.router = LLMRouter({"reporter": [ScriptedClient(["스크립트 답변"])]}, _Free())
    svc = CommandService(deps, deps.settings)
    assert svc.handle_text(111, "엔비디아 왜 팔았어?", T).text == "스크립트 답변"


def test_notifier_and_poller_use_bot_api():
    sent = []

    def handler(req: httpx.Request):
        sent.append((req.url.path, req.content))
        if req.url.path.endswith("/getUpdates"):
            return httpx.Response(200, json={"ok": True, "result": [
                {"update_id": 5, "message": {"chat": {"id": 111}, "text": "/status"}}]})
        return httpx.Response(200, json={"ok": True, "result": {}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    n = TelegramNotifier("TOKEN", [111], client=client)
    n.send("hi", buttons=[("승인", "approve:1")])
    assert sent[0][0] == "/botTOKEN/sendMessage" and b"inline_keyboard" in sent[0][1]

    class Svc:
        def handle_text(self, chat, text, now):
            from stockbot.telegram.commands import Reply
            return Reply(text=f"got {text}")

        def handle_callback(self, chat, data, now):
            return None

    p = TelegramPoller("TOKEN", Svc(), client=client)
    p.poll_once()
    assert p.offset == 6 and any(b"got /status" in c for _, c in sent)


def test_status_shows_product_rules(svc, deps):
    assert "개별 주식만" in svc.handle_text(111, "/status", T).text
    cfg = deps.runtime(); cfg.rules_paper.allow_leveraged_etf = True; deps.save_runtime(cfg)
    assert "레버리지·인버스" in svc.handle_text(111, "/status", T).text
