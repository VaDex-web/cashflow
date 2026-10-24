from __future__ import annotations

from typing import Any, Literal, TypedDict

Direction = Literal["in", "out"]
Severity = Literal["low", "medium", "high"]

EVENT_TYPES = ("contract", "invoice", "tax", "loan", "payroll", "manual")
EVENT_SOURCES = ("bank", "1c", "tax_calendar", "manual", "open_registry")
EVENT_STATUSES = ("expected", "paid", "overdue")
SCENARIO_TYPES = ("client_delay", "revenue_drop", "unplanned_expense", "fixed_cost_growth")

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

FIXED_COST_CATEGORIES = ("payroll", "rent", "utilities", "bank_fees")

GAP_PROBABILITY_LIKELY = 0.5
GAP_PROBABILITY_REPORT = 0.05
INTERVAL_LOW_Q = 0.10
INTERVAL_HIGH_Q = 0.90
INTERVAL_SCALE = 1.25
SHRINK_SHAPE = 0.5
SHRINK_DRIFT = 0.05
SHRINK_SHORT = 0.0


class Event(TypedDict, total=False):
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
    events: list[str]


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
    as_of: str
    current_balance: float
    comfort_balance: float
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
