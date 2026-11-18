"""Períodos, comparações e baldes de tempo.

Toda data é um dia de calendário LOCAL da unidade (started_at já vem na hora
local; não há conversão de fuso). Intervalos são fechados: [start, end].
"""

from __future__ import annotations

import calendar
import datetime as dt
import re
from dataclasses import dataclass
from typing import Optional, Tuple

from .errors import EngineError

MAX_PERIOD_DAYS = 731

PRESETS = (
    "today", "yesterday", "this_week", "last_week",
    "last_7_days", "last_30_days", "last_90_days",
    "this_month", "last_month", "this_quarter", "last_quarter",
    "this_year", "last_year", "month:AAAA-MM", "quarter:AAAA-Qn", "year:AAAA",
)
DEFAULT_PRESET = "last_90_days"


@dataclass(frozen=True)
class Period:
    start: dt.date
    end: dt.date
    preset: Optional[str] = None

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def to_dict(self, today: dt.date) -> dict:
        body = {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "basis": "started_at_unit_local",
        }
        if self.preset:
            body["from_preset"] = self.preset
        if self.start <= today <= self.end:
            body["in_progress"] = True
        if self.end > today:
            body["includes_future_days"] = True
        return body


def _quarter_bounds(year: int, q: int) -> Tuple[dt.date, dt.date]:
    start = dt.date(year, 3 * (q - 1) + 1, 1)
    end_month = 3 * q
    return start, dt.date(year, end_month, calendar.monthrange(year, end_month)[1])


def _month_bounds(year: int, month: int) -> Tuple[dt.date, dt.date]:
    return dt.date(year, month, 1), dt.date(year, month, calendar.monthrange(year, month)[1])


def resolve_period(
    today: dt.date, preset: Optional[str] = None, start: Optional[str] = None, end: Optional[str] = None
) -> Period:
    if start or end:
        if not (start and end):
            raise EngineError("invalid_period", "Informe --start e --end juntos (AAAA-MM-DD).")
        try:
            s, e = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
        except ValueError:
            raise EngineError("invalid_period", "Datas devem estar no formato AAAA-MM-DD.")
        if s > e:
            s, e = e, s
        return _checked(Period(s, e))

    preset = preset or DEFAULT_PRESET
    q_now = (today.month - 1) // 3 + 1
    monday = today - dt.timedelta(days=today.weekday())
    if preset == "today":
        p = Period(today, today, preset)
    elif preset == "yesterday":
        y = today - dt.timedelta(days=1)
        p = Period(y, y, preset)
    elif preset == "this_week":
        p = Period(monday, monday + dt.timedelta(days=6), preset)
    elif preset == "last_week":
        p = Period(monday - dt.timedelta(days=7), monday - dt.timedelta(days=1), preset)
    elif preset in ("last_7_days", "last_30_days", "last_90_days"):
        n = int(preset.split("_")[1])
        p = Period(today - dt.timedelta(days=n - 1), today, preset)
    elif preset == "this_month":
        p = Period(*_month_bounds(today.year, today.month), preset=preset)
    elif preset == "last_month":
        first = today.replace(day=1) - dt.timedelta(days=1)
        p = Period(*_month_bounds(first.year, first.month), preset=preset)
    elif preset == "this_quarter":
        p = Period(*_quarter_bounds(today.year, q_now), preset=preset)
    elif preset == "last_quarter":
        y, q = (today.year, q_now - 1) if q_now > 1 else (today.year - 1, 4)
        p = Period(*_quarter_bounds(y, q), preset=preset)
    elif preset == "this_year":
        p = Period(dt.date(today.year, 1, 1), dt.date(today.year, 12, 31), preset)
    elif preset == "last_year":
        p = Period(dt.date(today.year - 1, 1, 1), dt.date(today.year - 1, 12, 31), preset)
    elif re.fullmatch(r"month:\d{4}-\d{2}", preset):
        y, m = int(preset[6:10]), int(preset[11:13])
        if not 1 <= m <= 12:
            raise EngineError("invalid_period", f"Mês inválido em {preset}.")
        p = Period(*_month_bounds(y, m), preset=preset)
    elif re.fullmatch(r"quarter:\d{4}-Q[1-4]", preset):
        p = Period(*_quarter_bounds(int(preset[8:12]), int(preset[-1])), preset=preset)
    elif re.fullmatch(r"year:\d{4}", preset):
        y = int(preset[5:9])
        p = Period(dt.date(y, 1, 1), dt.date(y, 12, 31), preset)
    else:
        raise EngineError(
            "invalid_period",
            f"Preset de período desconhecido: {preset}.",
            hint="Use um destes: " + ", ".join(PRESETS) + ", ou --start/--end.",
        )
    return _checked(p)


def _checked(p: Period) -> Period:
    if p.days > MAX_PERIOD_DAYS:
        raise EngineError(
            "period_too_long",
            f"O período tem {p.days} dias; o máximo por consulta é {MAX_PERIOD_DAYS}.",
            hint="Divida a análise em anos (year:AAAA) ou use group_by month num período menor.",
        )
    return p


def _minus_one_year(d: dt.date) -> dt.date:
    try:
        return d.replace(year=d.year - 1)
    except ValueError:  # 29/02
        return d.replace(year=d.year - 1, day=28)


def comparison_period(p: Period, kind: str) -> Tuple[Period, str, bool]:
    """Devolve (período comparado, regra usada, janela ajustada?)."""
    if kind == "previous_year":
        if p.days > 366:
            cp, rule, _ = comparison_period(p, "previous_period")
            return cp, rule, True
        return Period(_minus_one_year(p.start), _minus_one_year(p.end)), "same_dates_previous_year", False
    if kind != "previous_period":
        raise EngineError("invalid_comparison", "compare_with aceita previous_period ou previous_year.")

    s, e = p.start, p.end
    if s.day == 1 and e == _month_bounds(s.year, s.month)[1]:
        prev = s - dt.timedelta(days=1)
        return Period(*_month_bounds(prev.year, prev.month)), "previous_calendar_month", False
    q = (s.month - 1) // 3 + 1
    if (s, e) == _quarter_bounds(s.year, q):
        y, pq = (s.year, q - 1) if q > 1 else (s.year - 1, 4)
        return Period(*_quarter_bounds(y, pq)), "previous_calendar_quarter", False
    if s == dt.date(s.year, 1, 1) and e == dt.date(s.year, 12, 31):
        return Period(dt.date(s.year - 1, 1, 1), dt.date(s.year - 1, 12, 31)), "previous_calendar_year", False
    length = p.days
    ce = s - dt.timedelta(days=1)
    return Period(ce - dt.timedelta(days=length - 1), ce), "same_length_immediately_before", False


# ----------------------------------------------------------------- baldes
TIME_BUCKETS = ("day", "week", "month", "quarter")
DOW_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DOW_LABELS_PT = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
HOUR_BLOCKS = (1, 2, 3, 4, 6, 8, 12)


def bucket_key(kind: str, day: str) -> str:
    d = dt.date.fromisoformat(day)
    if kind == "day":
        return day
    if kind == "week":
        iso = d.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    if kind == "month":
        return day[:7]
    if kind == "quarter":
        return f"{d.year}-Q{(d.month - 1) // 3 + 1}"
    raise ValueError(kind)


def bucket_bounds(kind: str, key: str) -> Tuple[dt.date, dt.date]:
    if kind == "day":
        d = dt.date.fromisoformat(key)
        return d, d
    if kind == "week":
        y, w = int(key[:4]), int(key[6:])
        start = dt.date.fromisocalendar(y, w, 1)
        return start, start + dt.timedelta(days=6)
    if kind == "month":
        return _month_bounds(int(key[:4]), int(key[5:7]))
    if kind == "quarter":
        return _quarter_bounds(int(key[:4]), int(key[-1]))
    raise ValueError(kind)


def shift_bucket_one_year(kind: str, key: str) -> Optional[str]:
    """Chave do mesmo balde um ano antes (para casar séries com previous_year)."""
    if kind == "day":
        return _minus_one_year(dt.date.fromisoformat(key)).isoformat()
    if kind == "week":
        y, w = int(key[:4]) - 1, int(key[6:])
        try:
            dt.date.fromisocalendar(y, w, 1)
        except ValueError:  # semana 53 que não existe no ano anterior
            return None
        return f"{y}-W{w:02d}"
    if kind == "month":
        return f"{int(key[:4]) - 1}{key[4:]}"
    if kind == "quarter":
        return f"{int(key[:4]) - 1}{key[4:]}"
    raise ValueError(kind)


def dow_key(day: str) -> str:
    return DOW_KEYS[dt.date.fromisoformat(day).weekday()]


def hour_block_key(started_at: str, size: int) -> str:
    hour = int(started_at[11:13])
    start = (hour // size) * size
    return f"{start:02d}-{start + size:02d}"


def iter_days(start: dt.date, end: dt.date):
    d = start
    while d <= end:
        yield d
        d += dt.timedelta(days=1)
