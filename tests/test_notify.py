import io
import sys

from stockbot.notify import ConsoleNotifier


def test_console_notifier_survives_cp949_console(monkeypatch):
    buf = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(buf, encoding="cp949"))
    ConsoleNotifier().send("🟡 승인 요청 #1", buttons=[("승인", "approve:1")])
    sys.stdout.flush()
    assert "승인 요청".encode("cp949") in buf.getvalue()
