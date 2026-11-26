from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Message:
    text: str
    buttons: list[tuple[str, str]] | None = None


class Notifier(Protocol):
    def send(self, text: str, buttons: list[tuple[str, str]] | None = None) -> None: ...


@dataclass
class ListNotifier:
    messages: list[Message] = field(default_factory=list)

    def send(self, text: str, buttons: list[tuple[str, str]] | None = None) -> None:
        self.messages.append(Message(text, buttons))


class ConsoleNotifier:
    def send(self, text: str, buttons: list[tuple[str, str]] | None = None) -> None:
        import sys

        extra = f"  [buttons: {', '.join(b[0] + '=' + b[1] for b in buttons)}]" if buttons else ""
        line = f"[notify] {text}{extra}"
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(line.encode(enc, errors="replace").decode(enc, errors="replace"))
