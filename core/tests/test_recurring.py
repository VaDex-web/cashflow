"""Регулярные платежи: период, сдвиг на выходные, плотные потоки."""
from datetime import date

import pandas as pd

from cashflow_core import categorize, detect_recurring, load_statement
from cashflow_core.calendar_ru import is_business_day, shift_to_business_day
from cashflow_core.recurring import find_patterns
from helpers import base_df


def _pats():
    c = categorize(load_statement(base_df()))
    return c, find_patterns(c)


def test_payroll_twice_a_month_with_backward_shift():
    _, pats = _pats()
    pay = sorted([p for p in pats if p.category == "payroll"], key=lambda p: p.anchor)
    assert [p.anchor for p in pay] == [10, 25]
    assert all(p.shift_rule == "backward" and p.period_days == 30 for p in pay)
    assert all(p.confidence > 0.8 for p in pay)


def test_tax_on_28th_forward_and_next_date_is_business_day():
    c, pats = _pats()
    tax = [p for p in pats if p.category == "taxes"]
    assert len(tax) == 1 and tax[0].anchor == 28 and tax[0].shift_rule == "forward"
    nd = tax[0].next_date(c["date"].max().date())
    assert is_business_day(nd)


def test_acquiring_daily_is_not_recurring_payment():
    _, pats = _pats()
    assert not any(p.counterparty == "ПАО «Банк»" and p.category == "revenue" for p in pats)


def test_contract_shape():
    rec = detect_recurring(load_statement(base_df()))
    assert rec and set(rec[0]) == {"name", "direction", "amount_avg", "period_days", "next_date", "confidence"}
    assert all(0 <= r["confidence"] <= 1 for r in rec)


def test_holiday_shift_rules():
    assert shift_to_business_day(date(2026, 1, 10), "backward") == date(2025, 12, 30)
    assert shift_to_business_day(date(2026, 2, 28), "forward") == date(2026, 3, 2)
    assert not is_business_day(date(2026, 11, 4))


def _enp_statement(late: dict[int, int], as_of: date) -> pd.DataFrame:
    """ЕНП 28-го (перенос вперёд) за 24 месяца; ``late`` — {номер месяца: на сколько дней позже}."""
    rows, bal = [], 5_000_000.0
    for k in range(24):
        y, m = divmod(2024 * 12 + 9 + k, 12)
        d = shift_to_business_day(date(y, m + 1, 28), "forward")
        d = date.fromordinal(d.toordinal() + late.get(k, 0))
        if d > as_of:
            break
        bal -= 300_000 + 1_000 * k
        rows.append({"operation_date": d.isoformat(), "amount": 300_000 + 1_000 * k, "direction": "Списание",
                     "counterparty_inn": "7727406020", "counterparty_name": "Казначейство России (ФНС России)",
                     "payment_purpose": "Единый налоговый платеж", "balance_eod": bal})
    for k in range(0, 720, 3):  # фон: выручка, чтобы выписка была похожа на настоящую
        d = date.fromordinal(date(2024, 10, 1).toordinal() + k)
        if d <= as_of:
            rows.append({"operation_date": d.isoformat(), "amount": 120_000, "direction": "Поступление",
                         "counterparty_inn": "6161000000", "counterparty_name": "ООО «Клиент»",
                         "payment_purpose": "Оплата по счёту", "balance_eod": bal})
    return pd.DataFrame(rows).sort_values("operation_date")


def test_enp_is_28th_even_with_late_payments():
    # как у C022/C041: в части месяцев ЕНП ушёл 29–30-го, один раз — 2-го следующего месяца
    as_of = date(2026, 9, 28)
    c = categorize(load_statement(_enp_statement({2: 5, 7: 1, 11: 2, 15: 1}, as_of)))
    tax = [p for p in find_patterns(c, as_of) if p.category == "taxes"]
    assert len(tax) == 1
    assert tax[0].anchor == 28 and tax[0].shift_rule == "forward"
    assert "~28-го числа" in tax[0].name
    assert tax[0].next_date(as_of) == date(2026, 10, 28)
    rec = [r for r in detect_recurring(c, as_of) if r["name"].startswith("Налоги")]
    assert rec and rec[0]["next_date"] == "2026-10-28"


def test_dividends_and_founder_loans_are_not_recurring():
    # дивиденды каждый квартал и возврат займа учредителю каждый месяц — решения владельца, а не обязательства
    rows = []
    for k in range(18):
        y, m = divmod(2025 * 12 + k, 12)
        rows.append({"operation_date": date(y, m + 1, 15).isoformat(), "amount": 400_000, "direction": "Списание",
                     "counterparty_inn": "", "counterparty_name": "Учредитель (физическое лицо)",
                     "payment_purpose": "Возврат беспроцентного займа учредителю по договору № 1/25", "balance_eod": 9e6})
        if m % 3 == 0:
            rows.append({"operation_date": date(y, m + 1, 16).isoformat(), "amount": 2_000_000, "direction": "Списание",
                         "counterparty_inn": "", "counterparty_name": "Участник общества (физическое лицо)",
                         "payment_purpose": "Выплата дивидендов за 1 квартал 2025 г. согласно решению участника",
                         "balance_eod": 7e6})
        rows.append({"operation_date": date(y, m + 1, 10).isoformat(), "amount": 300_000, "direction": "Списание",
                     "counterparty_inn": "", "counterparty_name": "Сотрудники",
                     "payment_purpose": "Заработная плата за месяц", "balance_eod": 8e6})
    c = categorize(load_statement(pd.DataFrame(rows)))
    names = [p.name for p in find_patterns(c)]
    assert any(n.startswith("Зарплата") for n in names)
    assert not any("Учредитель" in n or "Участник" in n or n.startswith("Прочее") or n.startswith("Кредиты") for n in names)
