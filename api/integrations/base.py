from __future__ import annotations

import hashlib
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from ..schemas import Event

_HOLIDAYS = {
    2024: ["01-01", "01-02", "01-03", "01-04", "01-05", "01-08", "02-23", "03-08", "04-29", "04-30", "05-01",
           "05-09", "05-10", "06-12", "11-04", "12-30", "12-31"],
    2025: ["01-01", "01-02", "01-03", "01-06", "01-07", "01-08", "05-01", "05-02", "05-08", "05-09", "06-12",
           "06-13", "11-03", "11-04", "12-31"],
    2026: ["01-01", "01-02", "01-05", "01-06", "01-07", "01-08", "01-09", "02-23", "03-09", "05-01", "05-11",
           "06-12", "11-04", "12-31"],
}
_WORKING = {2024: ["04-27", "11-02", "12-28"], 2025: ["11-01"], 2026: []}
HOLIDAYS = {date.fromisoformat(f"{y}-{md}") for y, l in _HOLIDAYS.items() for md in l}
WORKING_WEEKENDS = {date.fromisoformat(f"{y}-{md}") for y, l in _WORKING.items() for md in l}
_FIXED = [(1, d) for d in range(1, 9)] + [(2, 23), (3, 8), (5, 1), (5, 9), (6, 12), (11, 4)]


def is_business_day(d: date) -> bool:
    if d in WORKING_WEEKENDS:
        return True
    if d.weekday() >= 5:
        return False
    if d.year in _HOLIDAYS:
        return d not in HOLIDAYS
    return (d.month, d.day) not in _FIXED


def next_business_day(d: date) -> date:
    while not is_business_day(d):
        d += timedelta(days=1)
    return d


def prev_business_day(d: date) -> date:
    while not is_business_day(d):
        d -= timedelta(days=1)
    return d


class SourceEvent(Event):
    counterparty_inn: str = ""


def event_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(p) for p in parts)
    slug = re.sub(r"[^0-9A-Za-zА-Яа-я]+", "-", raw).strip("-")[:40]
    h = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:6]
    return f"{prefix}-{slug}-{h}" if slug else f"{prefix}-{h}"


@dataclass
class CompanyContext:
    company_id: str
    name: str = ""
    inn: str = ""
    legal_form: str = ""
    industry: str = ""
    df: pd.DataFrame = field(default_factory=pd.DataFrame)
    as_of: Optional[date] = None
    settings: dict[str, Any] = field(default_factory=dict)
    documents: dict[str, bytes] = field(default_factory=dict)
    fixtures_dir: Optional[Path] = None
    core: Any = None
    categorized: Optional[pd.DataFrame] = None

    FIXTURE_FILES = {"1c": "1c_export.json", "bank": "bank.json", "registry": "registry.json",
                     "contracts": "contracts.json", "invoices": "invoices.csv"}

    def document(self, kind: str) -> Optional[bytes]:
        if kind in self.documents:
            return self.documents[kind]
        if self.fixtures_dir is not None:
            p = self.fixtures_dir / self.FIXTURE_FILES.get(kind, kind)
            if p.exists():
                return p.read_bytes()
        return None

    def document_json(self, kind: str) -> Any:
        raw = self.document(kind)
        if raw is None:
            return None
        return json.loads(raw.decode("utf-8-sig"))

    def categories(self) -> pd.DataFrame:
        if self.categorized is None:
            from ..categories import categorize_simple

            if self.core is not None and len(self.df):
                try:
                    self.categorized = self.core.categorize(self.df)
                except Exception:
                    self.categorized = categorize_simple(self.df)
            else:
                self.categorized = categorize_simple(self.df) if len(self.df) else self.df
        return self.categorized


class Integration(ABC):
    name: str = ""
    title: str = ""
    source: str = "manual"
    description: str = ""

    @abstractmethod
    def fetch(self, company: CompanyContext) -> list[Event]:
        pass

    def message(self, company: CompanyContext, events: list[Event]) -> str:
        return ""


def as_date(v: Any) -> Optional[date]:
    if v is None or v == "":
        return None
    if isinstance(v, date):
        return v
    from ..statements import parse_date

    return parse_date(v)


def pick(d: dict[str, Any], *keys: str, default: Any = None) -> Any:
    low = {str(k).strip().lower(): v for k, v in d.items()}
    for k in keys:
        v = low.get(k.lower())
        if v not in (None, ""):
            return v
    return default


def to_float(v: Any, default: float = 0.0) -> float:
    from ..statements import parse_amount

    x = parse_amount(v)
    return default if x is None else float(x)


def counterparty_of(v: Any) -> tuple[str, str]:
    if isinstance(v, dict):
        return str(pick(v, "Наименование", "name", "Name", default="") or ""), str(pick(v, "ИНН", "inn", default="") or "")
    return str(v or ""), ""
