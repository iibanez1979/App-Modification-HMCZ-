"""Calendario laboral: lunes a viernes por defecto; sábado y domingo solo si el
administrador los habilita para un camión. Los festivos se excluyen siempre."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta


@dataclass(frozen=True)
class WorkCalendar:
    saturday: bool = False
    sunday: bool = False
    holidays: frozenset[date] = field(default_factory=frozenset)

    @classmethod
    def build(cls, saturday: bool, sunday: bool, holidays: Iterable[str | date]) -> "WorkCalendar":
        hol = {date.fromisoformat(h) if isinstance(h, str) else h for h in holidays if h}
        return cls(bool(saturday), bool(sunday), frozenset(hol))

    def is_workday(self, d: date) -> bool:
        if d in self.holidays:
            return False
        wd = d.weekday()
        if wd == 5:
            return self.saturday
        if wd == 6:
            return self.sunday
        return True

    def count(self, start: date | None, end: date | None) -> int:
        """Días hábiles entre start y end, ambos incluidos."""
        if start is None or end is None or end < start:
            return 0
        return sum(self.is_workday(start + timedelta(days=i)) for i in range((end - start).days + 1))

    def shift(self, d: date, n: int) -> date:
        """Mueve una fecha n días hábiles (negativo = hacia atrás).

        Si la fecha cae en un día no hábil, primero se ajusta al siguiente
        día hábil en la dirección del movimiento."""
        if n == 0:
            return d
        step = 1 if n > 0 else -1
        moved = 0
        cur = d
        while moved < abs(n):
            cur += timedelta(days=step)
            if self.is_workday(cur):
                moved += 1
        return cur

    def delay(self, planned: date | None, actual: date | None) -> int:
        """Días hábiles de atraso (positivo) o adelanto (negativo) de actual vs planned."""
        if planned is None or actual is None or planned == actual:
            return 0
        if actual > planned:
            return self.count(planned + timedelta(days=1), actual)
        return -self.count(actual + timedelta(days=1), planned)
