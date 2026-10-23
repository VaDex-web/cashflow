"""Форматирование для текстов на русском: суммы, даты."""
from __future__ import annotations

from datetime import date

MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
              "ноября", "декабря"]
MONTHS_NOM = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь",
              "ноябрь", "декабрь"]


def rub(x: float) -> str:
    """123456.7 → «123 457 ₽» (неразрывные пробелы)."""
    return f"{round(x):,}".replace(",", " ") + " ₽"


def day_month(d: date | str) -> str:
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    return f"{d.day} {MONTHS_GEN[d.month - 1]}"


def dmy(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def quoted(name: str | None) -> str:
    """Наименование контрагента для текста: уже с кавычками «» — как есть."""
    name = (name or "").strip()
    return name or "контрагент"
