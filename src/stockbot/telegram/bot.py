"""Minimal Telegram Bot API client over httpx: send messages with inline buttons, long-poll updates."""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

import httpx

log = logging.getLogger(__name__)
API = "https://api.telegram.org/bot{token}/{method}"


def _keyboard(buttons: list[tuple[str, str]] | None) -> dict | None:
    if not buttons:
        return None
    rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in rows]}


class TelegramNotifier:
    def __init__(self, token: str, chat_ids: list[int], client: httpx.Client | None = None):
        self.token, self.chat_ids = token, chat_ids
        self.client = client or httpx.Client(timeout=40)

    def _call(self, method: str, payload: dict) -> dict:
        r = self.client.post(API.format(token=self.token, method=method), json=payload)
        return r.json() if r.content else {}

    def send_to(self, chat_id: int, text: str, buttons: list[tuple[str, str]] | None = None) -> None:
        payload = {"chat_id": chat_id, "text": text[:4096]}
        kb = _keyboard(buttons)
        if kb:
            payload["reply_markup"] = kb
        try:
            self._call("sendMessage", payload)
        except httpx.HTTPError as e:
            log.warning("telegram send failed: %s", e)

    def send(self, text: str, buttons: list[tuple[str, str]] | None = None) -> None:
        for cid in self.chat_ids:
            self.send_to(cid, text, buttons)


class KVOffsetStore:
    def __init__(self, session_factory):
        self._sf = session_factory

    def load(self) -> int:
        from stockbot.settings_store import get_kv

        with self._sf() as s:
            return int(get_kv(s, "telegram_offset", 0) or 0)

    def save(self, offset: int) -> None:
        from stockbot.settings_store import set_kv

        with self._sf() as s:
            set_kv(s, "telegram_offset", offset)
            s.commit()


class TelegramPoller:
    """Long-polls getUpdates and routes messages / button presses to a CommandService."""

    def __init__(self, token: str, service, client: httpx.Client | None = None, poll_timeout: int = 25,
                 offset_store=None):
        self.notifier = TelegramNotifier(token, [], client)
        self.service = service
        self.offset_store = offset_store  # object with load() -> int and save(int); survives restarts
        self.offset = offset_store.load() if offset_store else 0
        self.poll_timeout = poll_timeout
        self._stop = threading.Event()

    def poll_once(self) -> int:
        resp = self.notifier._call("getUpdates", {"offset": self.offset, "timeout": self.poll_timeout,
                                                  "allowed_updates": ["message", "callback_query"]})
        updates = resp.get("result", []) if isinstance(resp, dict) else []
        now = datetime.now(timezone.utc)
        for u in updates:
            self.offset = max(self.offset, u["update_id"] + 1)
            if self.offset_store:
                self.offset_store.save(self.offset)
            try:
                if "message" in u:
                    m = u["message"]
                    chat = m["chat"]["id"]
                    reply = self.service.handle_text(chat, m.get("text", ""), now)
                elif "callback_query" in u:
                    cq = u["callback_query"]
                    chat = cq["message"]["chat"]["id"] if cq.get("message") else cq["from"]["id"]
                    self.notifier._call("answerCallbackQuery", {"callback_query_id": cq["id"]})
                    reply = self.service.handle_callback(chat, cq.get("data", ""), now)
                else:
                    continue
            except Exception as e:  # never let one update kill the loop
                log.exception("telegram handler failed")
                reply = None
                chat = None
            if reply is not None and chat is not None:
                self.notifier.send_to(chat, reply.text, reply.buttons)
        return len(updates)

    def run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception:
                log.exception("telegram poll failed")
                self._stop.wait(10)

    def start(self) -> threading.Thread:
        t = threading.Thread(target=self.run_forever, name="telegram-poller", daemon=True)
        t.start()
        return t

    def stop(self) -> None:
        self._stop.set()
