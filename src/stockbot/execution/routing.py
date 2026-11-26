from __future__ import annotations

from stockbot.config import ModeState
from stockbot.risk.rules import OrderIntent

AUTO_KINDS_SEMI = {"sell", "trim", "stop_loss", "switch_sell"}


def route(intents: list[OrderIntent], mode: ModeState, rebuy_auto: bool) -> tuple[list[OrderIntent], list[OrderIntent]]:
    """Split intents into (execute automatically, needs user approval)."""
    if mode.automation == "auto":
        return list(intents), []
    auto, need = [], []
    for i in intents:
        if i.kind in AUTO_KINDS_SEMI or (i.kind == "rebuy" and rebuy_auto):
            auto.append(i)
        else:
            need.append(i)
    return auto, need
