from __future__ import annotations

from sqlalchemy.orm import Session

from stockbot.config import RuntimeConfig
from stockbot.models import RuntimeSetting

_KEY = "runtime"


def load_runtime(session: Session) -> RuntimeConfig:
    row = session.get(RuntimeSetting, _KEY)
    return RuntimeConfig.model_validate(row.value) if row else RuntimeConfig()


def save_runtime(session: Session, cfg: RuntimeConfig) -> None:
    row = session.get(RuntimeSetting, _KEY)
    data = cfg.model_dump(mode="json")
    if row:
        row.value = data
    else:
        session.add(RuntimeSetting(key=_KEY, value=data))
