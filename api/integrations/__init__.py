"""Источники данных для прогноза. Все реализуют ``Integration.fetch(company) -> list[Event]``.

| name | класс | что даёт | Event.source |
|---|---|---|---|
| tax_calendar | TaxCalendar | ЕНП 28-го, авансы УСН, НДС по кварталам, налог на прибыль | tax_calendar |
| 1c | OneC | счета покупателям/от поставщиков, договоры, зарплатные ведомости | 1c |
| contracts | Contracts | договоры: график, предоплата, отсрочка (загрузка файлом) | manual |
| invoices | Invoices | счета: сумма, дата, срок оплаты (загрузка файлом) | manual |
| bank | Bank | графики кредитов, зарплатный проект, неисполненные платёжные поручения | bank |
| registry | Registry | статус контрагентов (риск задержки оплаты), госконтракты | open_registry |
| manual | Manual | ручной ввод через POST /events и /events/parse | manual |
"""
from __future__ import annotations

from .bank import Bank
from .base import CompanyContext, Integration, SourceEvent, event_id
from .contracts import Contracts
from .invoices import Invoices
from .manual import Manual, parse_text
from .onec import OneC
from .registry import CounterpartyStatus, Registry
from .tax_calendar import TaxCalendar


def all_integrations(registry_delay_days: int = 14) -> dict[str, Integration]:
    return {i.name: i for i in (TaxCalendar(), OneC(), Contracts(), Invoices(), Bank(), Registry(registry_delay_days),
                                Manual())}


__all__ = ["Integration", "CompanyContext", "SourceEvent", "CounterpartyStatus", "event_id", "all_integrations",
           "parse_text", "TaxCalendar", "OneC", "Contracts", "Invoices", "Bank", "Registry", "Manual"]
