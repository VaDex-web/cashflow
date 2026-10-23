"""Форматирование денег и дат для текстов «простым языком»."""
from __future__ import annotations

from datetime import date

_MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
               "сентября", "октября", "ноября", "декабря"]


def rub(x: float, approx: bool = False) -> str:
    """480000 -> '480 000 ₽' (с неразрывными пробелами). Крупные суммы округляются до тысяч."""
    v = float(x)
    if abs(v) >= 100_000:
        v = round(v / 1000) * 1000
    elif abs(v) >= 1000:
        v = round(v / 100) * 100
    s = f"{abs(v):,.0f}".replace(",", " ")
    sign = "−" if v < 0 else ""
    return f"{'~' if approx else ''}{sign}{s} ₽"


def day_month(d: date) -> str:
    """date(2026,11,17) -> '17 ноября'."""
    return f"{d.day} {_MONTHS_GEN[d.month - 1]}"


def plural_days(n: int) -> str:
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} день"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} дня"
    return f"{n} дней"
