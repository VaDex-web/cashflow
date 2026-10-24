from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pandas as pd

from ..textfmt import rub
from .base import CompanyContext, Integration, SourceEvent, as_date, counterparty_of, event_id, pick, to_float


@dataclass
class CounterpartyStatus:
    inn: str
    name: str
    risk_level: str = "low"
    reasons: list[str] = field(default_factory=list)
    delay_days: int = 0
    details: dict[str, Any] = field(default_factory=dict)


def assess(inn: str, name: str, info: dict[str, Any], delay_days: int) -> CounterpartyStatus:
    status = str(pick(info, "Статус", "status", default="Действующее"))
    bankrupt = bool(pick(info, "Банкротство", "bankruptcy", default=False))
    debt = to_float(pick(info, "ЗадолженностьПоНалогам", "tax_debt"))
    arb = int(to_float(pick(info, "АрбитражныеДелаОтветчик12мес", "arbitration")))
    fssp = int(to_float(pick(info, "ИсполнительныеПроизводства", "enforcement")))
    reasons = []
    if bankrupt:
        reasons.append("процедура банкротства (Федресурс)")
    if status.lower() not in ("действующее", "active", ""):
        reasons.append(f"статус в ЕГРЮЛ: {status.lower()}")
    if debt > 0:
        reasons.append(f"долг по налогам {rub(debt)}")
    if arb:
        reasons.append(f"{arb} арбитражных дел как ответчик за год")
    if fssp:
        reasons.append(f"{fssp} исполнительных производств")
    status_bad = status.lower() not in ("действующее", "active", "")
    score = 3 * bankrupt + 3 * status_bad + (2 if debt > 100_000 else 1 if debt > 0 else 0) + \
        (2 if arb >= 3 else 1 if arb else 0) + (1 if fssp else 0)
    level = "high" if score >= 4 else "medium" if score >= 2 else "low"
    days = int(to_float(pick(info, "СредняяПросрочкаДней", "avg_delay_days"), 0)) or (delay_days if level == "high" else 0)
    return CounterpartyStatus(inn, name, level, reasons, days, dict(info))


class Registry(Integration):
    name = "registry"
    title = "Открытые реестры"
    source = "open_registry"
    description = "Статус контрагентов (ЕГРЮЛ, банкротство, долги по налогам, суды, ФССП) и госконтракты"

    def __init__(self, delay_days: int = 14):
        self.delay_days = delay_days

    def check(self, company: CompanyContext) -> list[CounterpartyStatus]:
        data = company.document_json("registry")
        if data:
            out = []
            for c in pick(data, "Контрагенты", "counterparties", default=[]) or []:
                inn = str(pick(c, "ИНН", "inn", default=""))
                out.append(assess(inn, str(pick(c, "Наименование", "name", default="")), c, self.delay_days))
            return out
        return self._mock_checks(company)

    def _mock_checks(self, company: CompanyContext) -> list[CounterpartyStatus]:
        df, as_of = company.df, company.as_of
        if not len(df) or as_of is None:
            return []
        d = df[(df["direction"] == "in") & (pd.to_datetime(df["date"]).dt.date > as_of - timedelta(days=365))]
        d = d[d["counterparty_inn"].astype(str).str.len() == 10]
        out = []
        for inn, name in d.groupby("counterparty_inn")["counterparty_name"].first().items():
            h = int(hashlib.sha1(str(inn).encode()).hexdigest()[:8], 16)
            info = {"Статус": "Действующее", "Банкротство": h % 97 == 0,
                    "ЗадолженностьПоНалогам": float((h // 7) % 900_000) if h % 17 == 0 else 0.0,
                    "АрбитражныеДелаОтветчик12мес": (h // 11) % 6 if h % 9 == 0 else 0,
                    "ИсполнительныеПроизводства": (h // 13) % 3 if h % 17 == 0 else 0}
            st = assess(str(inn), str(name), info, self.delay_days)
            if st.reasons:
                st.reasons = [r + " (демонстрационные данные)" for r in st.reasons]
            st.details["mock"] = True
            out.append(st)
        return out

    def fetch(self, company: CompanyContext) -> list[SourceEvent]:
        data = company.document_json("registry") or {}
        out: list[SourceEvent] = []
        for gk in pick(data, "Госконтракты", "gov_contracts", default=[]) or []:
            name, inn = counterparty_of(pick(gk, "Заказчик", "customer", default=""))
            num = str(pick(gk, "РеестровыйНомер", "number", default=""))
            subj = str(pick(gk, "Предмет", "subject", default=""))
            for i, st in enumerate(pick(gk, "Этапы", "stages", default=[]) or [], 1):
                d, a = as_date(pick(st, "Дата", "date")), to_float(pick(st, "Сумма", "amount"))
                if d and a > 0:
                    out.append(SourceEvent(
                        id=event_id("gk", num, i), type="contract", direction="in", amount=round(a, 2), date=d,
                        source="open_registry", status="expected", counterparty=name or None, counterparty_inn=inn,
                        note=f"Госконтракт №{num} (ЕИС «Закупки»): {subj}. {pick(st, 'Описание', 'note', default='')}".strip()))
        return out

    def message(self, company: CompanyContext, events: list[SourceEvent]) -> str:
        checks = self.check(company)
        bad = [c for c in checks if c.risk_level == "high"]
        src = "" if company.document("registry") else " (демонстрационная проверка)"
        msg = f"Проверено контрагентов{src}: {len(checks)}, с высоким риском: {len(bad)}"
        if bad:
            msg += " (" + ", ".join(c.name for c in bad[:3]) + ")"
        if events:
            msg += f"; этапов госконтрактов: {len(events)}"
        return msg + "."
