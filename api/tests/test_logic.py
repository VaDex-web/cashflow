from __future__ import annotations

import logging
from datetime import date

import pandas as pd
import pytest

from api.integrations import Bank, CompanyContext, OneC, Registry, TaxCalendar, parse_text
from api.integrations.base import is_business_day, next_business_day
from api.integrations.contracts import contract_events, parse_contracts
from api.integrations.invoices import invoice_events, parse_invoices
from api.logging_setup import SensitiveDataFilter, mask
from api.plan_fact import EventView, build, reconcile
from api.statements import StatementError, parse_amount, parse_date, parse_direction, parse_statement_bytes

from .conftest import SYN


def ctx_for(cid: str, legal_form: str = "ООО") -> CompanyContext:
    rows, _ = parse_statement_bytes((SYN / "statements" / f"{cid}.csv").read_bytes())
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return CompanyContext(company_id=cid, name=cid, legal_form=legal_form, df=df, as_of=max(r["date"] for r in rows),
                          fixtures_dir=SYN / "integrations" / cid)


def test_parse_values():
    assert parse_amount("1 234,56") == 1234.56
    assert parse_amount("−300 ₽") == -300
    assert parse_amount("(500)") == -500
    assert parse_amount("1,234.50") == 1234.5
    assert parse_date("23.10.2026") == date(2026, 10, 23)
    assert parse_date("2026-10-23T10:00:00") == date(2026, 10, 23)
    assert parse_direction("Поступление") == "in" and parse_direction("Списание") == "out"
    assert parse_direction("Дт") == "out" and parse_direction("credit") == "in"


def test_parse_messy_statement_cp1251():
    text = ("Выписка по счёту ООО «Тест»\nПериод: 01.10.2026–23.10.2026\n"
            "Дата;Сумма;Контрагент;ИНН;Назначение платежа;Остаток\n"
            "01.10.2026;150 000,00;ООО «Клиент»;0012345678;Оплата по счету №5;1 150 000,00\n"
            "02.10.2026;-50 000,00;ИП Иванов;001234567890;;1 100 000,00\n"
            "02.10.2026;-50 000,00;ИП Иванов;001234567890;;1 100 000,00\n"
            "плохая строка;;;;;\n")
    rows, warnings = parse_statement_bytes(text.encode("cp1251"))
    assert len(rows) == 3
    assert rows[0]["direction"] == "in" and rows[1]["direction"] == "out" and rows[1]["amount"] == 50000
    assert rows[1]["counterparty_inn"] == "001234567890"
    assert any("одинаковые строки" in w for w in warnings)


def test_parse_dataset_format_keeps_inn_zeros():
    rows, _ = parse_statement_bytes((SYN / "statements" / "S02.csv").read_bytes())
    inns = {r["counterparty_inn"] for r in rows if "ФНС" not in r["counterparty_name"]}
    assert all(i == "" or i.startswith("00") for i in inns) and any(len(i) == 12 for i in inns)
    assert {r["direction"] for r in rows} == {"in", "out"}


def test_parse_errors():
    with pytest.raises(StatementError, match="пустой"):
        parse_statement_bytes(b"  ")
    with pytest.raises(StatementError, match="колонок"):
        parse_statement_bytes("просто текст без таблицы\nещё строка".encode())


def test_business_days():
    assert not is_business_day(date(2026, 11, 4))
    assert next_business_day(date(2026, 11, 28)) == date(2026, 11, 30)
    assert is_business_day(date(2025, 11, 1))


def test_tax_calendar_osno():
    c = ctx_for("S02")
    tc = TaxCalendar()
    assert tc.regime(c)["regime"] == "osno"
    ev = tc.fetch(c)
    dates = [e.date for e in ev]
    assert date(2026, 10, 28) in dates and date(2026, 11, 30) in dates
    oct28 = next(e for e in ev if e.date == date(2026, 10, 28))
    assert oct28.type == "tax" and oct28.source == "tax_calendar" and oct28.direction == "out"
    assert "НДС за 3 кв. 2026" in oct28.note and "налог на прибыль" in oct28.note
    assert 1_000_000 < oct28.amount < 2_300_000


def test_tax_calendar_usn_advances_only_quarterly():
    c = ctx_for("S01")
    c.settings["tax_regime"] = "usn6"
    ev = TaxCalendar().fetch(c)
    with_usn = [e for e in ev if "УСН 6%" in (e.note or "")]
    assert with_usn and all(e.date.month in (1, 4, 7, 10) or e.date.month == 3 for e in with_usn)
    oct28 = next(e for e in ev if e.date.month == 10 and e.date.year == 2026)
    plain = next(e for e in ev if e.date.month == 11)
    assert oct28.amount > plain.amount


def test_contract_schedule_prepayment_and_deferral():
    raw = ('[{"number": "17", "counterparty_name": "ООО «Покупатель»", "direction": "in", "total_amount": 1000000,'
           ' "signed_date": "2026-10-26", "prepayment_percent": 30, "deferral_days": 14, "delivery_date": "2026-11-10"}]')
    ev = contract_events(parse_contracts(raw.encode()), "manual", date(2026, 10, 23))
    assert [(e.date, e.amount) for e in ev] == [(date(2026, 10, 26), 300000.0), (date(2026, 11, 24), 700000.0)]
    assert "предоплата 30%" in ev[0].note and "отсрочка 14 дн." in ev[1].note
    sup = parse_contracts([{"Номер": "П-1", "ВидДоговора": "СПоставщиком", "Сумма": 500000, "Дата": "2026-11-02",
                            "ГрафикПлатежей": [{"Дата": "2026-11-05", "Сумма": 250000, "Этап": "аванс 50%"}]}])
    assert sup[0]["direction"] == "out" and sup[0]["schedule"][0]["amount"] == 250000


def test_invoices_statuses():
    inv = parse_invoices("number;direction;counterparty_name;amount;issue_date;due_date;paid_amount\n"
                         "1;in;ООО «А»;100000;2026-10-01;2026-10-10;0\n"
                         "2;in;ООО «Б»;100000;2026-10-01;2026-10-10;100000\n"
                         "3;in;ООО «В»;100000;2026-10-15;;40000\n")
    ev = invoice_events(inv, "manual", date(2026, 10, 23))
    st = {e.counterparty: (e.status, e.amount) for e in ev}
    assert st["ООО «А»"] == ("overdue", 100000.0)
    assert st["ООО «Б»"][0] == "paid"
    assert st["ООО «В»"] == ("expected", 60000.0)


def test_onec_bank_registry_fixtures():
    c = ctx_for("S02")
    ev = OneC().fetch(c)
    anchor = [e for e in ev if e.counterparty == "АО «ДонТрансЛогистика»" and e.status != "paid"]
    assert len(anchor) == 1 and anchor[0].status == "overdue" and anchor[0].amount == 2_322_000
    assert any(e.type == "payroll" for e in ev) and any(e.direction == "out" and e.type == "invoice" for e in ev)
    b = Bank().fetch(c)
    assert {e.type for e in b} >= {"loan", "payroll"} and all(e.source == "bank" for e in b)
    checks = Registry(14).check(c)
    bad = [x for x in checks if x.risk_level == "high"]
    assert [x.name for x in bad] == ["АО «ДонТрансЛогистика»"] and bad[0].delay_days == 14
    assert any("долг по налогам" in r for r in bad[0].reasons)


def test_bank_mock_from_history_without_file():
    c = ctx_for("S03")
    c.fixtures_dir = None
    ev = Bank().fetch(c)
    loans = [e for e in ev if e.type == "loan"]
    assert loans and all(e.date > c.as_of and e.amount == 245000 for e in loans if "КД-2024/0187" in e.note)
    assert not any(e.type == "payroll" for e in ev)


@pytest.mark.parametrize("text,direction,amount,day", [
    ("клиент обещал заплатить 300 000 ₽ 20-го", "in", 300000, date(2026, 11, 20)),
    ("в декабре куплю оборудование за 1 млн рублей", "out", 1_000_000, date(2026, 12, 1)),
    ("ООО «Ромашка» вернёт долг 150 тыс 5 ноября", "in", 150000, date(2026, 11, 5)),
    ("штраф 45 000 р. 30.10", "out", 45000, date(2026, 10, 30)),
    ("получим предоплату 1,5 млн через 2 недели", "in", 1_500_000, date(2026, 11, 6)),
    ("купим станок за 1.2 млн 10 ноября", "out", 1_200_000, date(2026, 11, 10)),
    ("купим станок за 1,2 млн 10.11", "out", 1_200_000, date(2026, 11, 10)),
    ("заплатить поставщику 300 тыс 28.10", "out", 300_000, date(2026, 10, 28)),
    ("клиент Ромашка обещал 2.5 млн 1-го", "in", 2_500_000, date(2026, 11, 1)),
])
def test_parse_text(text, direction, amount, day):
    ev, understood = parse_text(text, date(2026, 10, 23))
    assert (ev.direction, ev.amount, ev.date) == (direction, amount, day)
    assert ev.source == "manual" and understood


def test_parse_text_counterparty():
    for text, cp in (("клиент Ромашка обещал заплатить 300 тыс 20-го", "Ромашка"),
                     ("поставщик Агро Трейд ждёт оплату 1,2 млн 30.10", "Агро Трейд"),
                     ("ООО «Ромашка» вернёт долг 150 тыс 5 ноября", "ООО «Ромашка»"),
                     ("клиент обещал заплатить 300 000 ₽ 20-го", None)):
        ev, understood = parse_text(text, date(2026, 10, 23))
        assert ev.counterparty == cp, text
        assert cp is None or cp in understood


def test_parse_text_needs_amount():
    with pytest.raises(ValueError, match="сумму"):
        parse_text("клиент обещал заплатить 20-го", date(2026, 10, 23))


def test_plan_fact_overdue_paid_and_texts():
    tx = pd.DataFrame([
        {"date": "2026-10-09", "amount": 140000.0, "direction": "in", "counterparty_name": "ООО «Кофейня Ромашка»",
         "counterparty_inn": "001", "purpose": "Оплата по договору №47"},
        {"date": "2026-10-21", "amount": 135000.0, "direction": "in", "counterparty_name": "ООО «Ресторанный двор Городок»",
         "counterparty_inn": "002", "purpose": "Оплата счета №318"},
        {"date": "2026-10-20", "amount": 900000.0, "direction": "out", "counterparty_name": "ООО «Неожиданный»",
         "counterparty_inn": "003", "purpose": "Оплата"},
    ])
    events = [
        EventView("a", "invoice", "in", 210000, date(2026, 10, 16), "1c", "expected", "ООО «Пекарня Лакомка»", "", "Счёт №301"),
        EventView("b", "contract", "in", 140000, date(2026, 10, 9), "1c", "expected", "ООО «Кофейня Ромашка»", "001"),
        EventView("c", "invoice", "in", 210000, date(2026, 10, 21), "1c", "expected", "ООО «Ресторанный двор Городок»", "002", "Счёт №318"),
    ]
    m = {x.event_id: x for x in reconcile(events, tx, date(2026, 10, 23))}
    assert m["a"].status == "overdue"
    assert m["b"].status == "paid" and m["b"].paid_date == date(2026, 10, 9)
    assert m["c"].paid_amount == 135000.0
    rows = build(tx, events, [], date(2026, 10, 23), list(m.values()), weeks=3)
    texts = [d["text"] for r in rows for d in r["deviations"]]
    assert any("ООО «Пекарня Лакомка» не оплатил счёт №301 на 210" in t for t in texts)
    assert any("частичная оплата" in t for t in texts)
    assert any(t.startswith("Внеплановое списание 900") for t in texts)
    assert [r["period"] for r in rows] == ["2026-10-05", "2026-10-12", "2026-10-19"]


def test_log_masking():
    s = mask("ИНН 0012345678 и 001234567890, сумма 1 234 567,89 ₽ и 250000.00, ООО «Ромашка», a@b.ru")
    assert "0012345678" not in s and "001234567890" not in s
    assert "1 234 567" not in s and "250000" not in s and "Ромашка" not in s and "a@b.ru" not in s
    assert "GET /api/companies/S02/forecast 200 15ms" == mask("GET /api/companies/S02/forecast 200 15ms")
    assert mask("Uvicorn running on http://127.0.0.1:8000") == "Uvicorn running on http://127.0.0.1:8000"


def test_access_log_keeps_status_and_time():
    import logging

    from api.logging_setup import SensitiveDataFilter

    def run(name, msg):
        rec = logging.LogRecord(name, logging.INFO, __file__, 1, msg, (), None)
        SensitiveDataFilter().filter(rec)
        return rec.msg

    assert run("api.http", "POST /api/companies 200 123ms") == "POST /api/companies 200 123ms"
    assert run("api.http", "GET /api/companies/x/forecast 401 1534ms") == "GET /api/companies/x/forecast 401 1534ms"
    assert "<сумма>" in run("api.service", "оплата 200 123 ₽") and "0012345678" not in run("api.http", "GET /x/0012345678 200 1ms")


def test_log_filter_on_record(caplog):
    lg = logging.getLogger("api.test")
    lg.addFilter(SensitiveDataFilter())
    with caplog.at_level(logging.INFO, logger="api.test"):
        lg.info("payment %s from %s", 1500000.55, "ООО «Секрет»")
    assert "1500000" not in caplog.text and "Секрет" not in caplog.text
