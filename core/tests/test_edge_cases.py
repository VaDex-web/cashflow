"""Граничные случаи: ничего не падает, есть понятные warnings."""
import logging
from datetime import timedelta

import pandas as pd

from cashflow_core import forecast
from datagen import generate_statement
from helpers import FAST, base_df, last_date


def _ok(r, horizon=30):
    assert len(r["daily"]) == horizon
    assert isinstance(r["warnings"], list)


def test_short_histories():
    for days in (10, 45):
        r = forecast(generate_statement(days=days), [], 30, **FAST)
        _ok(r)
        assert any("История" in w for w in r["warnings"])


def test_empty_and_single_row():
    r = forecast(pd.DataFrame(), [], 30, **FAST)
    assert r["daily"] == [] or len(r["daily"]) == 30
    one = generate_statement(days=40).iloc[:1]
    _ok(forecast(one, [], 30, **FAST))


def test_overdraft_start():
    df = generate_statement(days=200, start_balance=-300_000_000)
    r = forecast(df, [], 30, **FAST, model="ets")
    assert r["risks"] and r["risks"][0]["probability"] > 0.9
    assert "овердрафт" in r["risks"][0]["reason"]


def test_giant_client_warning():
    r = forecast(generate_statement(days=200, giant_client=True), [], 30, **FAST, model="ets")
    assert any("Один клиент" in w for w in r["warnings"])


def test_all_purposes_empty():
    _ok(forecast(generate_statement(days=200, empty_purpose_share=1.0), [], 30, **FAST, model="ets"))


def test_bad_events_and_new_counterparty():
    df = base_df()
    d = (last_date(df) + timedelta(days=5)).date().isoformat()
    ev = [{"type": "invoice", "direction": "in", "amount": 100000, "date": d, "counterparty": "ООО «Новичок»"},
          {"type": "invoice", "direction": "sideways", "amount": 1, "date": d},
          {"type": "tax", "amount": "abc", "date": d}]
    r = forecast(df, ev, 30, **FAST, model="ets")
    _ok(r)
    assert sum("пропущено" in w for w in r["warnings"]) == 2
    assert any("новых контрагентов" in w for w in r["warnings"])


def test_outliers_and_holidays_horizon():
    df = generate_statement(days=380, start="2024-12-20")  # горизонт попадает на январские каникулы
    big = df.iloc[[40]].copy()
    big["amount"] = 5e7
    big["direction"] = "in"
    df = pd.concat([df, big]).sort_values("date").reset_index(drop=True)
    df["balance_eod"] = df["balance_eod"]  # остаток не сходится в один день — это тоже граничный случай
    _ok(forecast(df, [], 30, **FAST, model="ets"))


def test_logs_have_no_inn_names_or_amounts():
    records = []

    class H(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    lg = logging.getLogger("cashflow_core")
    h = H()
    lg.addHandler(h)
    old = lg.level
    lg.setLevel(logging.DEBUG)
    try:
        df = base_df()
        forecast(df, [], 30, **FAST, model="ets")
    finally:
        lg.removeHandler(h)
        lg.setLevel(old)
    text = "\n".join(records)
    assert records
    for inn in set(df["counterparty_inn"]):
        assert inn not in text
    for name in set(df["counterparty_name"]):
        assert name not in text
    assert "₽" not in text
