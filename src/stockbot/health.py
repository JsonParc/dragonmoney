from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from stockbot.models import HealthEvent
from stockbot.orders_store import aware_utc, naive_utc

FAIL_STREAK = 3
DATA_COMPONENTS = {"prices", "news", "debate", "quotes"}  # job:* failures alert but do not block buying


class Health:
    def __init__(self, session_factory):
        self._sf = session_factory

    def record(self, component: str, ok: bool, detail: str, now: datetime | None = None) -> None:
        with self._sf() as s:
            s.add(HealthEvent(component=component, ok=ok, detail=detail[:500],
                              at=naive_utc(now or datetime.now(timezone.utc))))
            s.commit()

    def _recent(self, s, component: str, n: int) -> list[HealthEvent]:
        return s.execute(select(HealthEvent).where(HealthEvent.component == component)
                         .order_by(HealthEvent.id.desc()).limit(n)).scalars().all()

    def failing(self) -> list[str]:
        with self._sf() as s:
            comps = s.execute(select(HealthEvent.component).distinct()).scalars().all()
            return [c for c in comps if c in DATA_COMPONENTS
                    and len(ev := self._recent(s, c, FAIL_STREAK)) == FAIL_STREAK and not any(e.ok for e in ev)]

    def degraded(self) -> bool:
        return bool(self.failing())

    def status(self) -> dict[str, dict]:
        out = {}
        with self._sf() as s:
            for c in s.execute(select(HealthEvent.component).distinct()).scalars().all():
                ev = self._recent(s, c, 20)
                streak = 0
                for e in ev:
                    if e.ok:
                        break
                    streak += 1
                out[c] = {"ok": ev[0].ok, "detail": ev[0].detail, "at": aware_utc(ev[0].at), "fail_streak": streak}
        return out
