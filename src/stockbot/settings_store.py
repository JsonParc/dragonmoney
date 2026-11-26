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


def get_kv(session: Session, key: str, default=None):
    row = session.get(RuntimeSetting, f"kv:{key}")
    return row.value.get("v", default) if row else default


def set_kv(session: Session, key: str, value) -> None:
    row = session.get(RuntimeSetting, f"kv:{key}")
    if row:
        row.value = {"v": value}
    else:
        session.add(RuntimeSetting(key=f"kv:{key}", value={"v": value}))
