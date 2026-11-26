from datetime import timedelta

import pytest
from exec_helpers import NOW, OPEN, add_i, buy, buy_i, quotes, rebuy_i, sell_i, stop_i, switch_buy_i

from stockbot.broker.paper import PaperBroker
from stockbot.config import ModeState
from stockbot.execution.approvals import ApprovalQueue
from stockbot.execution.executor import Executor
from stockbot.execution.routing import route
from stockbot.notify import ListNotifier


@pytest.fixture
def queue(session_factory):
    return ApprovalQueue(session_factory)


@pytest.fixture
def notifier():
    return ListNotifier()


@pytest.fixture
def executor(session_factory, queue, notifier):
    broker = PaperBroker(session_factory, quotes(100.0, ts=OPEN), initial_cash=10_000)
    broker.place(buy("A", 5, key="seed"), NOW)
    return Executor(session_factory, broker, queue, notifier)


def test_semi_routing():
    auto, need = route([sell_i(), stop_i(), rebuy_i(), buy_i(), add_i(), switch_buy_i()], ModeState(), rebuy_auto=True)
    assert {i.kind for i in auto} == {"sell", "stop_loss", "rebuy"}
    assert {i.kind for i in need} == {"new_buy", "add", "switch_buy"}
    assert route([buy_i()], ModeState(automation="auto"), True)[1] == []
    assert route([rebuy_i()], ModeState(), rebuy_auto=False)[1][0].kind == "rebuy"


def test_double_approve_and_expiry(queue):
    aid = queue.create(order_id=1, expires_at=NOW + timedelta(hours=1))
    assert queue.approve(aid, NOW) == "ok" and queue.approve(aid, NOW) == "already"
    aid2 = queue.create(order_id=2, expires_at=NOW)
    assert queue.approve(aid2, NOW + timedelta(seconds=1)) == "expired"
    aid3 = queue.create(order_id=3, expires_at=NOW + timedelta(hours=1))
    assert queue.reject(aid3, NOW) == "ok" and queue.approve(aid3, NOW) == "already"


def test_executor_flow(executor, notifier):
    executor.stage([sell_i("A"), buy_i("B")], ModeState(), True, approval_expires_at=OPEN)
    assert any("approve:" in b[1] for m in notifier.messages for b in (m.buttons or []))
    results = executor.execute_ready(OPEN)
    assert [r.status for r in results] == ["filled"]  # B not approved -> expired, not executed


def test_approved_buy_executes(executor, queue):
    rep = executor.stage([buy_i("B")], ModeState(), True, approval_expires_at=OPEN)
    assert queue.approve(rep.approval_ids[0], NOW) == "ok"
    assert [r.status for r in executor.execute_ready(OPEN)] == ["filled"]


def test_stage_is_idempotent(executor):
    executor.stage([sell_i("A")], ModeState(), True, approval_expires_at=OPEN)
    rep = executor.stage([sell_i("A")], ModeState(), True, approval_expires_at=OPEN)
    assert rep.duplicates == 1
    assert len(executor.execute_ready(OPEN)) == 1 and executor.execute_ready(OPEN) == []


def test_execute_now(executor):
    out = executor.execute_now([sell_i("A")], NOW)
    assert out[0].status == "filled"
