"""Банк (внутренняя интеграция, мок): графики кредитов, зарплатный проект, созданные платёжные поручения.

Источник — ``bank.json`` (тестовые данные или загруженный файл)::

    {"Кредиты": [{"Договор", "Кредитор", "График": [{"Дата", "Сумма"}]}],
     "ЗарплатныйПроект": {"Ведомости": [{"Дата", "Вид", "Сумма", "Сотрудников"}]},
     "ПлатежныеПоручения": [{"Номер", "Дата", "Сумма", "Получатель": {"Наименование", "ИНН"}, "Назначение", "Статус"}]}

Если файла нет, мок «знает» то же, что банк видит у себя по счёту клиента: ежемесячные платежи по
кредитам и лизингу и выплаты по зарплатному проекту — из истории операций (дата и сумма последнего платежа).
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from .base import (CompanyContext, Integration, SourceEvent, as_date, counterparty_of, event_id, next_business_day, pick,
                   prev_business_day, to_float)

_LOAN_RX = re.compile(r"(?i)погашени\w* (?:основного долга|кредит)|по кредитному договору|кредитн\w+ лини|лизингов")
_PAY_RX = re.compile(r"(?i)заработн|\(аванс\)|аванс по заработ")
_DOGOVOR_RX = re.compile(r"(?i)договор\w*\s*№\s*([\w/.-]+)")


def _type_for_order(purpose: str) -> str:
    p = purpose.lower()
    if "аренд" in p or "договор" in p:
        return "contract"
    if "счет" in p or "счёт" in p:
        return "invoice"
    if "налог" in p or "енп" in p:
        return "tax"
    return "manual"


class Bank(Integration):
    name = "bank"
    title = "Банк"
    source = "bank"
    description = "Кредиты и их графики, зарплатный проект, созданные платёжные поручения"
    horizon_days = 60

    def fetch(self, company: CompanyContext) -> list[SourceEvent]:
        data = company.document_json("bank")
        return self._from_file(company, data) if data else self._from_history(company)

    def _from_file(self, company: CompanyContext, data: dict[str, Any]) -> list[SourceEvent]:
        out: list[SourceEvent] = []
        for loan in pick(data, "Кредиты", "loans", default=[]) or []:
            contract = str(pick(loan, "Договор", "contract", default=""))
            lender = str(pick(loan, "Кредитор", "lender", default="Банк"))
            for p in pick(loan, "График", "schedule", default=[]) or []:
                d, a = as_date(pick(p, "Дата", "date")), to_float(pick(p, "Сумма", "amount"))
                if d and a > 0:
                    out.append(SourceEvent(id=event_id("bank-loan", contract, d), type="loan", direction="out",
                                           amount=round(a, 2), date=d, source="bank", status="expected", counterparty=lender,
                                           note=f"Платёж по кредитному договору №{contract} (график банка)"))
        zp = pick(data, "ЗарплатныйПроект", "payroll", default={}) or {}
        for v in pick(zp, "Ведомости", "registries", default=[]) or []:
            d, a = as_date(pick(v, "Дата", "date")), to_float(pick(v, "Сумма", "amount"))
            if d and a > 0:
                kind = str(pick(v, "Вид", "kind", default="Зарплата"))
                n = pick(v, "Сотрудников", "employees", default="")
                out.append(SourceEvent(id=event_id("bank-zp", d, kind), type="payroll", direction="out", amount=round(a, 2),
                                       date=d, source="bank", status="expected",
                                       counterparty=f"Сотрудники ({n} чел.)" if n else "Сотрудники",
                                       note=f"Зарплатный проект: {kind.lower()}, реестр к исполнению"))
        for po in pick(data, "ПлатежныеПоручения", "payment_orders", default=[]) or []:
            d, a = as_date(pick(po, "Дата", "date")), to_float(pick(po, "Сумма", "amount"))
            if not d or a <= 0:
                continue
            name, inn = counterparty_of(pick(po, "Получатель", "recipient", default=""))
            purpose = str(pick(po, "Назначение", "purpose", default=""))
            status = str(pick(po, "Статус", "status", default="создано"))
            out.append(SourceEvent(id=event_id("bank-pp", pick(po, "Номер", default=""), d), type=_type_for_order(purpose),
                                   direction="out", amount=round(a, 2), date=d, source="bank", status="expected",
                                   counterparty=name or None, counterparty_inn=inn,
                                   note=f"Платёжное поручение №{pick(po, 'Номер', default='б/н')} ({status.lower()}): {purpose[:120]}"))
        return out

    def _from_history(self, company: CompanyContext) -> list[SourceEvent]:
        df, as_of = company.df, company.as_of
        if not len(df) or as_of is None:
            return []
        d = df.copy()
        d["date"] = pd.to_datetime(d["date"]).dt.date
        recent = d[(d["date"] > as_of - timedelta(days=100)) & (d["direction"] == "out")]
        out: list[SourceEvent] = []
        bankish = recent["counterparty_name"].str.contains(r"(?i)банк|лизинг", regex=True)
        loans = recent[bankish & recent["purpose"].str.contains(_LOAN_RX)]
        groups: dict[str, list[Any]] = defaultdict(list)
        for r in loans.itertuples(index=False):
            m = _DOGOVOR_RX.search(r.purpose)
            groups[(m.group(1) if m else r.counterparty_name)].append(r)
        end = as_of + timedelta(days=self.horizon_days)
        for key, rows in groups.items():
            if len(rows) < 2:
                continue
            rows.sort(key=lambda r: r.date)
            day = int(np.median([r.date.day for r in rows]))
            last = rows[-1]
            for k in range(1, 4):
                y, m = divmod(as_of.year * 12 + as_of.month - 1 + k - 1, 12)
                due = next_business_day(date(y, m + 1, min(day, 28 if m + 1 == 2 else 30)))
                if as_of < due <= end:
                    out.append(SourceEvent(id=event_id("bank-loan", key, due), type="loan", direction="out",
                                           amount=round(float(last.amount), 2), date=due, source="bank", status="expected",
                                           counterparty=str(last.counterparty_name) or None,
                                           counterparty_inn=str(last.counterparty_inn or ""),
                                           note=f"Платёж по договору №{key} — график банка (по последним платежам)"))
        pay = recent[recent["purpose"].str.contains(_PAY_RX)]
        if len(pay) >= 2:
            kinds = {"аванс": pay[pay["purpose"].str.contains(r"(?i)аванс")],
                     "зарплата": pay[~pay["purpose"].str.contains(r"(?i)аванс")]}
            for kind, rows in kinds.items():
                if len(rows) < 2:
                    continue
                by_day = rows.groupby("date")["amount"].sum()
                day = int(np.median([x.day for x in by_day.index]))
                amount = float(by_day.iloc[-1])
                for k in range(0, 3):
                    y, m = divmod(as_of.year * 12 + as_of.month - 1 + k, 12)
                    due = prev_business_day(date(y, m + 1, min(day, 28)))
                    if as_of < due <= end:
                        out.append(SourceEvent(id=event_id("bank-zp", due, kind), type="payroll", direction="out",
                                               amount=round(amount, 2), date=due, source="bank", status="expected",
                                               counterparty="Сотрудники",
                                               note=f"Зарплатный проект: {kind} (сумма последнего реестра)"))
        return out

    def message(self, company: CompanyContext, events: list[SourceEvent]) -> str:
        src = "данные банка" if company.document("bank") else "мок по истории счёта"
        by = defaultdict(int)
        for e in events:
            by[e.type] += 1
        return f"{src}: кредиты — {by['loan']}, зарплатный проект — {by['payroll']}, платёжные поручения — " \
               f"{sum(v for k, v in by.items() if k not in ('loan', 'payroll'))}."
