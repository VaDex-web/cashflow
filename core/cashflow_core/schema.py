"""Типы JSON-сущностей из контракта (docs/contract.md) и общие константы.

Все публичные функции ядра возвращают обычные dict/list, совместимые с JSON.
TypedDict-ы ниже — документация формы этих словарей и подсказки для mypy.
"""
from __future__ import annotations

from typing import Any, Literal, TypedDict

Direction = Literal["in", "out"]
Severity = Literal["low", "medium", "high"]

EVENT_TYPES = ("contract", "invoice", "tax", "loan", "payroll", "manual")
EVENT_SOURCES = ("bank", "1c", "tax_calendar", "manual", "open_registry")
EVENT_STATUSES = ("expected", "paid", "overdue")
SCENARIO_TYPES = ("client_delay", "revenue_drop", "unplanned_expense", "fixed_cost_growth")

#: Код категории -> человекочитаемое название (для UI).
CATEGORIES: dict[str, str] = {
    "revenue": "Выручка от клиентов",
    "payroll": "Зарплата",
    "rent": "Аренда",
    "taxes": "Налоги и взносы",
    "suppliers": "Поставщики/закупки",
    "utilities": "Коммунальные/связь/подписки",
    "loans": "Кредиты и проценты",
    "bank_fees": "Банковские комиссии",
    "transfers": "Переводы между своими счетами",
    "other": "Прочее",
}

#: Категории, которые по смыслу бывают только в одном направлении.
CATEGORY_DIRECTIONS: dict[str, tuple[str, ...]] = {
    "revenue": ("in",),
    "payroll": ("out",),
    "rent": ("out",),
    "taxes": ("out",),
    "suppliers": ("out",),
    "utilities": ("out",),
    "bank_fees": ("out",),
    "loans": ("in", "out"),
    "transfers": ("in", "out"),
    "other": ("in", "out"),
}

#: Постоянные расходы для сценария fixed_cost_growth.
FIXED_COST_CATEGORIES = ("payroll", "rent", "utilities", "bank_fees")

#: Порог вероятности, начиная с которого разрыв считается «вероятным».
GAP_PROBABILITY_LIKELY = 0.5
#: Минимальная вероятность, при которой риск попадает в список risks.
GAP_PROBABILITY_REPORT = 0.05
#: Квантили интервала: balance_low = P10, balance_high = P90 (80% интервал).
INTERVAL_LOW_Q = 0.10
INTERVAL_HIGH_Q = 0.90
#: Калибровочный множитель ширины интервалов Monte Carlo (подобран бэктестом, см. core/reports/metrics.md).
INTERVAL_SCALE = 1.0


class Event(TypedDict, total=False):
    """Ожидаемое будущее событие (договор, счёт, налог, кредит, зарплата, ручной ввод)."""

    id: str
    type: str
    direction: Direction
    amount: float
    date: str
    source: str
    status: str
    counterparty: str
    note: str


class DailyPoint(TypedDict, total=False):
    date: str
    balance_p50: float
    balance_low: float
    balance_high: float
    events: list[str]          # необязательное: id событий на эту дату


class Risk(TypedDict):
    date: str
    shortfall_amount: float
    probability: float
    severity: Severity
    reason: str
    recommendations: list[str]


class Recurring(TypedDict):
    name: str
    direction: Direction
    amount_avg: float
    period_days: int
    next_date: str
    confidence: float


class ForecastResult(TypedDict):
    company_id: str
    generated_at: str
    horizon_days: int
    as_of: str                 # необязательное: дата последней операции
    current_balance: float     # необязательное: фактический остаток на as_of
    daily: list[DailyPoint]
    risks: list[Risk]
    recurring: list[Recurring]
    sources_used: list[str]
    warnings: list[str]


class ScenarioDelta(TypedDict, total=False):
    first_gap_date: str | None
    max_shortfall: float


class ScenarioResult(TypedDict):
    base: ForecastResult
    scenario: ForecastResult
    delta: ScenarioDelta


class Scenario(TypedDict):
    type: str
    params: dict[str, Any]
