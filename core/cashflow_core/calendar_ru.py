"""Производственный календарь РФ: рабочие и нерабочие дни, сдвиг платежей.

Для 2024–2026 даты взяты из постановлений Правительства (с переносами).
Для остальных лет — общее правило ТК РФ (ст. 112): фиксированные праздники,
а праздник, выпавший на выходной, переносится на следующий рабочий день
(кроме январских каникул).
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache
from typing import Iterable, Literal

import numpy as np
import pandas as pd

ShiftRule = Literal["backward", "forward"]


def _d(s: str) -> date:
    return date.fromisoformat(s)


#: Нерабочие будние дни (праздники и переносы), утверждённые постановлениями.
_OFFICIAL_HOLIDAYS: dict[int, list[str]] = {
    2024: [
        "2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08",
        "2024-02-23", "2024-03-08", "2024-04-29", "2024-04-30", "2024-05-01", "2024-05-09",
        "2024-05-10", "2024-06-12", "2024-11-04", "2024-12-30", "2024-12-31",
    ],
    2025: [
        "2025-01-01", "2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07", "2025-01-08",
        "2025-05-01", "2025-05-02", "2025-05-08", "2025-05-09", "2025-06-12", "2025-06-13",
        "2025-11-03", "2025-11-04", "2025-12-31",
    ],
    2026: [
        "2026-01-01", "2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08",
        "2026-01-09", "2026-02-23", "2026-03-09", "2026-05-01", "2026-05-11", "2026-06-12",
        "2026-11-04", "2026-12-31",
    ],
}

#: Рабочие субботы (переносы).
_OFFICIAL_WORKING_WEEKENDS: dict[int, list[str]] = {
    2024: ["2024-04-27", "2024-11-02", "2024-12-28"],
    2025: ["2025-11-01"],
    2026: [],
}

_FIXED_HOLIDAYS = [(1, d) for d in range(1, 9)] + [(2, 23), (3, 8), (5, 1), (5, 9), (6, 12), (11, 4)]


@lru_cache(maxsize=64)
def _year_sets(year: int) -> tuple[frozenset[date], frozenset[date]]:
    """Вернуть (нерабочие будни, рабочие выходные) для года."""
    if year in _OFFICIAL_HOLIDAYS:
        return (
            frozenset(_d(s) for s in _OFFICIAL_HOLIDAYS[year]),
            frozenset(_d(s) for s in _OFFICIAL_WORKING_WEEKENDS.get(year, [])),
        )
    off: set[date] = set()
    for m, dd in _FIXED_HOLIDAYS:
        h = date(year, m, dd)
        if h.weekday() < 5:
            off.add(h)
        elif m != 1:  # перенос на ближайший рабочий день (январские — по постановлению, тут упрощаем)
            nxt = h + timedelta(days=1)
            while nxt.weekday() >= 5 or nxt in off:
                nxt += timedelta(days=1)
            off.add(nxt)
    return frozenset(off), frozenset()


def is_business_day(d: date | pd.Timestamp) -> bool:
    """True, если день рабочий по производственному календарю РФ."""
    if isinstance(d, pd.Timestamp):
        d = d.date()
    return _is_bd(d)


@lru_cache(maxsize=20000)
def _is_bd(d: date) -> bool:
    off, work = _year_sets(d.year)
    if d in work:
        return True
    if d in off:
        return False
    return d.weekday() < 5


def is_holiday(d: date | pd.Timestamp) -> bool:
    """True для праздничного/перенесённого нерабочего дня, выпавшего на будни."""
    if isinstance(d, pd.Timestamp):
        d = d.date()
    return d in _year_sets(d.year)[0]


@lru_cache(maxsize=20000)
def shift_to_business_day(d: date, rule: ShiftRule = "forward") -> date:
    """Сдвинуть дату на ближайший рабочий день вперёд или назад."""
    step = timedelta(days=1 if rule == "forward" else -1)
    out = d
    for _ in range(20):
        if is_business_day(out):
            return out
        out += step
    return d


def business_day_flags(dates: Iterable[date | pd.Timestamp]) -> np.ndarray:
    """Вектор флагов «рабочий день» для набора дат."""
    return np.array([is_business_day(x) for x in dates], dtype=bool)


def _calendar_table_build(start: date, end: date) -> pd.DataFrame:
    index = pd.date_range(start, end, freq="D")
    bd = business_day_flags(index)
    prev_bd = np.concatenate([[is_business_day(index[0] - pd.Timedelta(days=1))], bd[:-1]])
    next_bd = np.concatenate([bd[1:], [is_business_day(index[-1] + pd.Timedelta(days=1))]])
    dim = index.days_in_month.values
    dom = index.day.values
    return pd.DataFrame(
        {
            "dow": index.dayofweek.values,
            "dom": dom,
            "month": index.month.values,
            "days_to_month_end": dim - dom,
            "is_business_day": bd.astype(int),
            "after_break": (bd & ~prev_bd).astype(int),  # первый рабочий день после выходных/праздников
            "before_break": (bd & ~next_bd).astype(int),
            "is_holiday": np.array([is_holiday(x) for x in index], dtype=int),
            "week_of_month": ((dom - 1) // 7).astype(int),
        },
        index=index,
    )


@lru_cache(maxsize=1)
def _calendar_table() -> pd.DataFrame:
    return _calendar_table_build(date(2015, 1, 1), date(2035, 12, 31))


def calendar_features(index: pd.DatetimeIndex) -> pd.DataFrame:
    """Календарные признаки для моделей потоков (без утечек будущего). Таблица считается один раз."""
    tab = _calendar_table()
    if len(index) and (index.min() < tab.index[0] or index.max() > tab.index[-1]):
        return _calendar_table_build(index.min().date(), index.max().date()).reindex(index)
    if len(index) and len(index) == (index[-1] - index[0]).days + 1:
        return tab.loc[index[0]:index[-1]]  # непрерывный дневной ряд — быстрый срез
    return tab.reindex(index)
