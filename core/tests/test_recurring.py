"""Регулярные платежи: период, сдвиг на выходные, плотные потоки."""
from datetime import date

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
