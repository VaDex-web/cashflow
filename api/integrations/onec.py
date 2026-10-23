"""1С (внешняя интеграция, мок-адаптер): читает JSON-выгрузку из учётной системы.

Ожидаемый формат (как в ``data/synthetic/integrations/<id>/1c_export.json``)::

    {"Формат": "...", "ДатаВыгрузки": "...", "Организация": {"Наименование", "ИНН"},
     "Документы": {
        "СчетНаОплатуПокупателю": [{"Номер", "Дата", "Контрагент": {"Наименование", "ИНН"}, "Сумма",
                                    "СрокОплаты", "Оплачен", "СуммаОплаты", "Комментарий"}],
        "СчетОтПоставщика": [...],
        "Договор": [{"Номер", "Дата", "ВидДоговора", "Контрагент", "Сумма", "ПредоплатаПроцент",
                     "ОтсрочкаДней", "ГрафикПлатежей": [{"Дата", "Сумма", "Этап"}]}],
        "ВедомостьНаВыплатуЗарплаты": [{"Номер", "ДатаВыплаты", "Вид", "Сумма", "Сотрудников"}]}}

Реальный обмен (HTTP-сервис 1С / EnterpriseData) подключается заменой метода ``load``.
"""
from __future__ import annotations

from typing import Any

from ..textfmt import rub
from .base import CompanyContext, Integration, SourceEvent, as_date, event_id, pick, to_float
from .contracts import contract_events, parse_contracts
from .invoices import invoice_events, parse_invoices


class OneC(Integration):
    name = "1c"
    title = "1С: Бухгалтерия"
    source = "1c"
    description = "Выставленные и полученные счета, договоры, зарплатные ведомости"

    def load(self, company: CompanyContext) -> dict[str, Any] | None:
        return company.document_json("1c")

    def fetch(self, company: CompanyContext) -> list[SourceEvent]:
        data = self.load(company)
        if not data:
            return []
        docs = pick(data, "Документы", "documents", default={}) or {}
        events: list[SourceEvent] = []
        events += invoice_events(parse_invoices(pick(docs, "СчетНаОплатуПокупателю", default=[]) or [], "in"),
                                 "1c", company.as_of, prefix="1c-inv")
        events += invoice_events(parse_invoices(pick(docs, "СчетОтПоставщика", default=[]) or [], "out"),
                                 "1c", company.as_of, prefix="1c-sup")
        events += contract_events(parse_contracts(pick(docs, "Договор", default=[]) or []), "1c", company.as_of,
                                  prefix="1c-dog")
        for v in pick(docs, "ВедомостьНаВыплатуЗарплаты", default=[]) or []:
            d = as_date(pick(v, "ДатаВыплаты", "Дата"))
            amount = to_float(pick(v, "Сумма"))
            if d is None or amount <= 0:
                continue
            kind = str(pick(v, "Вид", default="Зарплата"))
            n = pick(v, "Сотрудников", default="")
            events.append(SourceEvent(
                id=event_id("1c-zp", pick(v, "Номер", default=""), d), type="payroll", direction="out",
                amount=round(amount, 2), date=d, source="1c", status="expected",
                counterparty=f"Сотрудники ({n} чел.)" if n else "Сотрудники",
                note=f"Ведомость на выплату: {kind.lower()} №{pick(v, 'Номер', default='б/н')}"))
        return events

    def message(self, company: CompanyContext, events: list[SourceEvent]) -> str:
        if self.load(company) is None:
            return "Выгрузка из 1С ещё не загружена — загрузите файл выгрузки, и счета и договоры попадут в прогноз."
        od = [e for e in events if e.status == "overdue" and e.direction == "in"]
        msg = f"Получено из 1С: {len(events)} платежей по счетам, договорам и ведомостям."
        if od:
            msg += f" Просрочено оплат от клиентов: {len(od)} на {rub(sum(e.amount for e in od))}."
        return msg
