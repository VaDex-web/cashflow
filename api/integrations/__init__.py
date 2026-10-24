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
