from __future__ import annotations

import datetime as dt
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator

Direction = Literal["in", "out"]
Severity = Literal["low", "medium", "high"]
EventType = Literal["contract", "invoice", "tax", "loan", "payroll", "manual"]
EventSource = Literal["bank", "1c", "tax_calendar", "manual", "open_registry"]
EventStatus = Literal["expected", "paid", "overdue"]
ScenarioType = Literal["client_delay", "revenue_drop", "unplanned_expense", "fixed_cost_growth"]
IntegrationName = Literal["bank", "1c", "tax_calendar", "registry", "contracts", "invoices"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class EventCreate(_Model):
    type: EventType = "manual"
    direction: Direction
    amount: float = Field(gt=0, description="сумма, ₽ (> 0)")
    date: dt.date = Field(description="YYYY-MM-DD")
    source: EventSource = "manual"
    status: EventStatus = "expected"
    counterparty: Optional[str] = None
    note: Optional[str] = None


class Event(EventCreate):
    id: str


class EventUpdate(_Model):
    type: Optional[EventType] = None
    direction: Optional[Direction] = None
    amount: Optional[float] = Field(default=None, gt=0)
    date: Optional[dt.date] = None
    status: Optional[EventStatus] = None
    counterparty: Optional[str] = None
    note: Optional[str] = None


class EventParseRequest(_Model):
    text: str = Field(min_length=3, max_length=500, examples=["клиент обещал заплатить 300 000 ₽ 20-го"])


class EventParseResult(_Model):
    event: EventCreate
    understood: str
    saved: Optional[Event] = None


class Scenario(_Model):
    type: ScenarioType
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_params(self) -> "Scenario":
        p = self.params
        if self.type == "client_delay":
            if not str(p.get("counterparty_or_event_id") or "").strip():
                raise ValueError("Укажите клиента или платёж (counterparty_or_event_id)")
            w = _num(p.get("weeks", 2), "weeks")
            if not 2 <= w <= 4:
                raise ValueError("Задержка клиента — от 2 до 4 недель (weeks)")
            p["weeks"] = int(w)
        elif self.type == "revenue_drop":
            v = _num(p.get("percent"), "percent")
            if not 10 <= v <= 30:
                raise ValueError("Падение выручки — от 10 до 30% (percent)")
        elif self.type == "unplanned_expense":
            if _num(p.get("amount"), "amount") <= 0:
                raise ValueError("Сумма внепланового расхода должна быть больше нуля")
            try:
                dt.date.fromisoformat(str(p.get("date")))
            except ValueError:
                raise ValueError("Дата внепланового расхода — в формате ГГГГ-ММ-ДД") from None
        elif self.type == "fixed_cost_growth":
            v = _num(p.get("percent"), "percent")
            if not 0 < v <= 200:
                raise ValueError("Рост постоянных расходов — больше 0 и не больше 200% (percent)")
        return self


def _num(v: Any, name: str) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        raise ValueError(f"Параметр {name} должен быть числом") from None


class DailyPoint(_Model):
    date: str
    balance_p50: float
    balance_low: float
    balance_high: float
    events: Optional[list[str]] = None


class Risk(_Model):
    date: str
    shortfall_amount: float
    probability: float = Field(ge=0, le=1)
    severity: Severity
    reason: str
    recommendations: list[str] = Field(default_factory=list)
    kind: Optional[Literal["gap", "below_comfort"]] = None


class Recurring(_Model):
    name: str
    direction: Direction
    amount_avg: float
    period_days: int
    next_date: str
    confidence: float

    @field_validator("period_days", mode="before")
    @classmethod
    def _int(cls, v: Any) -> int:
        return int(round(float(v)))


class ForecastResult(_Model):
    company_id: str
    generated_at: str
    horizon_days: int
    daily: list[DailyPoint]
    risks: list[Risk]
    recurring: list[Recurring]
    sources_used: list[str]
    warnings: Optional[list[str]] = None
    current_balance: Optional[float] = None
    as_of: Optional[str] = None
    comfort_balance: Optional[float] = None


class ScenarioDelta(_Model):
    first_gap_date: Optional[str] = None
    max_shortfall: Optional[float] = None

    @model_serializer(mode="plain")
    def _always_both(self) -> dict[str, Any]:
        return {"first_gap_date": self.first_gap_date, "max_shortfall": self.max_shortfall}


class ScenarioResult(_Model):
    base: ForecastResult
    scenario: ForecastResult
    delta: ScenarioDelta


class Deviation(_Model):
    event_id: str
    text: str


class PlanFactRow(_Model):
    period: str
    planned_in: float
    actual_in: float
    planned_out: float
    actual_out: float
    deviations: list[Deviation] = Field(default_factory=list)


class LoginRequest(_Model):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class LoginResponse(_Model):
    access_token: str
    token_type: Literal["bearer"] = "bearer"


class Health(_Model):
    status: Literal["ok"] = "ok"
    core: Optional[str] = None


class CompanyCreated(_Model):
    company_id: str
    rows: Optional[int] = None
    warnings: Optional[list[str]] = None


class CompanyInfo(_Model):
    company_id: str
    company_name: str
    legal_form: str
    industry: str
    first_operation_date: Optional[str] = None
    last_operation_date: Optional[str] = None
    operations_count: int = 0


class Me(_Model):
    username: str
    company_id: Optional[str] = None
    company_name: Optional[str] = None


class MeUpdate(_Model):
    company_id: str = Field(min_length=1, max_length=64)


class CompanySettingsIn(_Model):
    safety_cushion: Optional[float] = Field(default=None, ge=0, description="комфортный минимум на счёте, ₽")
    tax_regime: Optional[Literal["usn_income", "usn_income_expense", "osno", "eshn"]] = None


class CompanySettings(_Model):
    safety_cushion: float = Field(description="действующий комфортный минимум, ₽ (риск считается от него)")
    safety_cushion_default: float = Field(description="по умолчанию — расходы примерно за 7 дней")
    safety_cushion_custom: bool
    tax_regime: Optional[str] = None
    tax_regime_estimated: Optional[dict[str, Any]] = None


class CategorySummary(_Model):
    category: str
    direction: Direction
    total: float
    count: int
    share: float


class CategoryTransaction(_Model):
    date: str
    amount: float
    direction: Direction
    counterparty_name: str = ""
    counterparty_inn: str = ""
    purpose: str = ""
    balance_eod: Optional[float] = None
    category: str = ""
    category_confidence: float = 0.0


class CategoriesResponse(_Model):
    summary: list[CategorySummary]
    transactions: list[CategoryTransaction]


class SyncResponse(_Model):
    name: str
    status: str = "ok"
    events_added: int = 0
    synced_at: str
    events_updated: Optional[int] = None
    message: Optional[str] = None


class TransactionIn(_Model):
    model_config = ConfigDict(extra="allow")

    date: Optional[str] = None
    amount: Optional[float | str] = None
    direction: Optional[str] = None
    counterparty_name: Optional[str] = ""
    counterparty_inn: Optional[str] = ""
    purpose: Optional[str] = ""
    balance_eod: Optional[float | str] = None
