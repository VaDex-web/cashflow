from __future__ import annotations

import csv
import io
import json
from datetime import date, timedelta
from typing import Any

from ..textfmt import dmy, rub
from .base import CompanyContext, Integration, SourceEvent, as_date, counterparty_of, event_id, pick, to_float

DEFAULT_DEFERRAL = 10


def _dir(v: Any, default: str) -> str:
    s = str(v or "").strip().lower()
    if s in ("out", "списание", "поставщик", "входящий", "от поставщика", "supplier", "получен"):
        return "out"
    if s in ("in", "поступление", "покупатель", "исходящий", "клиенту", "customer", "выставлен"):
        return "in"
    return default


def parse_invoices(raw: bytes | str | list | dict, default_direction: str = "in") -> list[dict[str, Any]]:
    if isinstance(raw, (bytes, str)):
        text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw
        t = text.lstrip()
        if t.startswith(("[", "{")):
            data = json.loads(t)
        else:
            first = t.splitlines()[0]
            data = list(csv.DictReader(io.StringIO(t), delimiter=";" if first.count(";") >= first.count(",") else ","))
    else:
        data = raw
    if isinstance(data, dict):
        data = pick(data, "invoices", "Счета", default=[]) or []
    out = []
    for r in data or []:
        if not isinstance(r, dict):
            continue
        name, inn = counterparty_of(pick(r, "Контрагент", "counterparty", default=""))
        issued = as_date(pick(r, "issue_date", "Дата", "дата", "date"))
        due = as_date(pick(r, "due_date", "СрокОплаты", "срок_оплаты", "срок"))
        deferral = pick(r, "deferral_days", "ОтсрочкаДней")
        if due is None and issued is not None:
            due = issued + timedelta(days=int(to_float(deferral, DEFAULT_DEFERRAL)))
        amount = to_float(pick(r, "amount", "Сумма", "сумма"))
        paid_flag = str(pick(r, "Оплачен", "paid", default="")).strip().lower() in ("true", "1", "да", "yes")
        paid = to_float(pick(r, "paid_amount", "СуммаОплаты", "оплачено"), amount if paid_flag else 0.0)
        out.append({
            "number": str(pick(r, "number", "Номер", "номер", default="б/н")),
            "direction": _dir(pick(r, "direction", "направление", "вид"), default_direction),
            "counterparty_name": str(pick(r, "counterparty_name", default=name) or name),
            "counterparty_inn": str(pick(r, "counterparty_inn", "ИНН", "инн", default=inn) or inn),
            "amount": amount, "paid_amount": paid, "issue_date": issued, "due_date": due,
            "paid_date": as_date(pick(r, "paid_date", "ДатаОплаты")),
            "note": str(pick(r, "note", "Комментарий", "comment", default="") or ""),
        })
    return [x for x in out if x["amount"] > 0 and x["due_date"] is not None]


def invoice_events(invoices: list[dict[str, Any]], source: str, as_of: date | None, prefix: str = "inv") -> list[SourceEvent]:
    out: list[SourceEvent] = []
    today = as_of or date.today()
    for x in invoices:
        rest = x["amount"] - x["paid_amount"]
        paid = rest <= 0.01 * x["amount"]
        amount = x["amount"] if paid else rest
        status = "paid" if paid else ("overdue" if x["due_date"] < today else "expected")
        what = "Счёт" if x["direction"] == "in" else "Счёт поставщика"
        note = f"{what} №{x['number']}" + (f" от {dmy(x['issue_date'])}" if x["issue_date"] else "") + \
               f", срок оплаты {dmy(x['due_date'])}"
        if 0 < x["paid_amount"] < x["amount"]:
            note += f", оплачено частично {rub(x['paid_amount'])} из {rub(x['amount'])}"
        if x["note"]:
            note += f". {x['note']}"
        out.append(SourceEvent(
            id=event_id(prefix, x["direction"], x["number"], x["counterparty_inn"] or x["counterparty_name"]),
            type="invoice", direction=x["direction"], amount=round(float(amount), 2), date=x["due_date"],
            source=source, status=status, counterparty=x["counterparty_name"] or None, note=note,
            counterparty_inn=x["counterparty_inn"]))
    return out


class Invoices(Integration):
    name = "invoices"
    title = "Счета"
    source = "manual"
    description = "Выставленные клиентам и полученные от поставщиков счета: сумма, дата, срок оплаты"

    def fetch(self, company: CompanyContext) -> list[SourceEvent]:
        raw = company.document("invoices")
        if raw is None:
            return []
        return invoice_events(parse_invoices(raw), self.source, company.as_of)

    def message(self, company: CompanyContext, events: list[SourceEvent]) -> str:
        if company.document("invoices") is None:
            return "Файл со счетами ещё не загружен."
        od = [e for e in events if e.status == "overdue"]
        return f"Счетов: {len(events)}, просрочено: {len(od)}" + (f" на {rub(sum(e.amount for e in od))}" if od else "") + "."
