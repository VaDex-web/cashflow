"""Договоры с клиентами и поставщиками: суммы, график платежей, отсрочка, предоплата → события.

Формат загрузки — JSON (список или ``{"contracts": [...]}``) или CSV (``;``/``,``), ключи по-русски
или по-английски::

    {"number": "П-2026/33", "counterparty_name": "ООО «Северный ритейл»", "counterparty_inn": "00…",
     "direction": "in",               # in — с покупателем, out — с поставщиком
     "total_amount": 960000, "signed_date": "2026-10-20",
     "prepayment_percent": 30,        # предоплата при подписании
     "deferral_days": 10,             # отсрочка окончательного расчёта после поставки/акта
     "delivery_date": "2026-12-05",   # поставка/акт (если нет графика)
     "monthly_amount": 0, "start_date": "", "end_date": "",   # абонентский договор: платёж каждый месяц
     "schedule": [{"date": "2026-10-27", "amount": 288000, "note": "предоплата 30%"}]}

Если есть ``schedule`` — события ровно по графику; иначе: предоплата в дату подписания и остаток
в дату поставки + отсрочка; для абонентских — ежемесячно с учётом отсрочки.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import date, timedelta
from typing import Any

from ..textfmt import dmy, rub
from .base import CompanyContext, Integration, SourceEvent, as_date, counterparty_of, event_id, next_business_day, pick, to_float


def _direction(v: Any) -> str:
    s = str(v or "").strip().lower()
    if s in ("out", "списание", "споставщиком", "с поставщиком", "поставщик", "расход", "supplier"):
        return "out"
    if s.startswith(("спост", "пост")) and "постав" in s:
        return "out"
    return "in"


def parse_contracts(raw: bytes | str | list | dict) -> list[dict[str, Any]]:
    if isinstance(raw, (bytes, str)):
        text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw
        t = text.lstrip()
        if t.startswith(("[", "{")):
            data = json.loads(t)
        else:
            delim = ";" if t.splitlines()[0].count(";") >= t.splitlines()[0].count(",") else ","
            data = list(csv.DictReader(io.StringIO(t), delimiter=delim))
    else:
        data = raw
    if isinstance(data, dict):
        data = pick(data, "contracts", "Договоры", "Договор", default=[]) or []
    out = []
    for c in data or []:
        if not isinstance(c, dict):
            continue
        name, inn = counterparty_of(pick(c, "counterparty", "Контрагент", default=""))
        name = str(pick(c, "counterparty_name", "контрагент_наименование", default=name) or name)
        inn = str(pick(c, "counterparty_inn", "инн", "ИНН", default=inn) or inn)
        sched_raw = pick(c, "schedule", "ГрафикПлатежей", "график", default=[]) or []
        if isinstance(sched_raw, str):      # CSV: «2026-10-27:288000|2026-12-15:672000»
            sched_raw = [{"date": p.split(":")[0], "amount": p.split(":")[1]} for p in sched_raw.split("|") if ":" in p]
        schedule = [{"date": as_date(pick(s, "date", "Дата")), "amount": to_float(pick(s, "amount", "Сумма")),
                     "note": str(pick(s, "note", "Этап", "Описание", "kind", default="") or "")}
                    for s in sched_raw if isinstance(s, dict)]
        out.append({
            "number": str(pick(c, "number", "Номер", "номер", default="б/н")),
            "counterparty_name": name, "counterparty_inn": inn,
            "direction": _direction(pick(c, "direction", "ВидДоговора", "вид", default="in")),
            "total_amount": to_float(pick(c, "total_amount", "Сумма", "сумма", "amount")),
            "signed_date": as_date(pick(c, "signed_date", "Дата", "дата", "date")),
            "prepayment_percent": to_float(pick(c, "prepayment_percent", "ПредоплатаПроцент", "предоплата")),
            "deferral_days": int(to_float(pick(c, "deferral_days", "ОтсрочкаДней", "отсрочка"))),
            "delivery_date": as_date(pick(c, "delivery_date", "ДатаПоставки", "end_date", "ДатаОкончания")),
            "monthly_amount": to_float(pick(c, "monthly_amount", "ЕжемесячныйПлатеж")),
            "start_date": as_date(pick(c, "start_date", "ДатаНачала")),
            "end_date": as_date(pick(c, "end_date", "ДатаОкончания")),
            "schedule": [s for s in schedule if s["date"] and s["amount"] > 0],
            "note": str(pick(c, "note", "Комментарий", "comment", default="") or ""),
        })
    return out


def contract_events(contracts: list[dict[str, Any]], source: str, as_of: date | None, prefix: str = "ct",
                    horizon_days: int = 120) -> list[SourceEvent]:
    """События по договорам (прошлые этапы тоже — для план-факта)."""
    out: list[SourceEvent] = []
    lo = (as_of or date.today()) - timedelta(days=90)
    hi = (as_of or date.today()) + timedelta(days=horizon_days)
    for c in contracts:
        num, d = c["number"], c["direction"]
        rows: list[tuple[date, float, str]] = []
        if c["schedule"]:
            rows = [(s["date"], s["amount"], s["note"] or "платёж по графику") for s in c["schedule"]]
        elif c["monthly_amount"] > 0 and c["start_date"]:
            cur = c["start_date"]
            stop = c["end_date"] or hi
            while cur <= stop and cur <= hi:
                rows.append((next_business_day(cur + timedelta(days=c["deferral_days"])), c["monthly_amount"],
                             f"ежемесячный платёж за {cur.month:02d}.{cur.year}"))
                y, m = (cur.year + (cur.month == 12), cur.month % 12 + 1)
                cur = date(y, m, min(cur.day, 28))
        elif c["total_amount"] > 0 and c["signed_date"]:
            total, p = c["total_amount"], max(0.0, min(c["prepayment_percent"], 100.0)) / 100
            if p > 0:
                rows.append((c["signed_date"], total * p, f"предоплата {p:.0%}"))
            if p < 1:
                deliv = c["delivery_date"] or (c["signed_date"] + timedelta(days=30))
                rows.append((next_business_day(deliv + timedelta(days=c["deferral_days"])), total * (1 - p),
                             "окончательный расчёт" + (f" (отсрочка {c['deferral_days']} дн. после поставки)" if c["deferral_days"] else "")))
        for i, (when, amount, what) in enumerate(rows, 1):
            if not (lo <= when <= hi) or amount <= 0:
                continue
            note = f"Договор №{num}" + (f" от {dmy(c['signed_date'])}" if c["signed_date"] else "") + f": {what}"
            if c.get("note"):
                note += f". {c['note']}"
            out.append(SourceEvent(
                id=event_id(prefix, num, i, when), type="contract", direction=d, amount=round(float(amount), 2),
                date=when, source=source, status="expected", counterparty=c["counterparty_name"] or None,
                note=note, counterparty_inn=c["counterparty_inn"]))
    return out


class Contracts(Integration):
    name = "contracts"
    title = "Договоры"
    source = "manual"          # загружены пользователем файлом; из 1С — source="1c"
    description = "Договоры с клиентами и поставщиками: график, предоплата, отсрочка"

    def fetch(self, company: CompanyContext) -> list[SourceEvent]:
        raw = company.document("contracts")
        if raw is None:
            return []
        return contract_events(parse_contracts(raw), self.source, company.as_of)

    def message(self, company: CompanyContext, events: list[SourceEvent]) -> str:
        if company.document("contracts") is None:
            return "Файл договоров не загружен: POST /api/companies/{id}/integrations/contracts/upload"
        total_in = sum(e.amount for e in events if e.direction == "in")
        return f"Платежей по договорам: {len(events)}, поступлений на {rub(total_in)}."
