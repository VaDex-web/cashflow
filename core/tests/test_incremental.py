import time
from datetime import timedelta

import pandas as pd

from cashflow_core import build_state, load_statement, update_forecast
from helpers import FAST, base_df


def test_update_moves_start_and_matches_balance():
    full = load_statement(base_df())
    cut = full["date"].max() - pd.Timedelta(days=10)
    hist, new = full[full["date"] <= cut], full[full["date"] > cut]
    ev = [{"id": "late", "type": "invoice", "direction": "in", "amount": 7777777, "date": (cut + pd.Timedelta(days=2)).date().isoformat()}]
    t = time.time()
    st = build_state(hist, ev, 30, model="ets", **FAST)
    t_build = time.time() - t
    rows = [{"date": d.strftime("%Y-%m-%d"), "amount": a, "direction": di, "counterparty_name": n,
             "counterparty_inn": i, "purpose": p} for d, a, di, n, i, p in
            zip(new["date"], new["amount"], new["direction"], new["counterparty_name"], new["counterparty_inn"], new["purpose"])]
    t = time.time()
    st, r = update_forecast(st, rows)
    t_upd = time.time() - t
    assert st.as_of == full["date"].max().date()
    assert abs(st.start_balance - full["balance_eod"].iloc[-1]) < 0.01
    assert r["daily"][0]["date"] == (st.as_of + timedelta(days=1)).isoformat()
    assert "late" in st.last_update["events_overdue"]
    assert any("просроч" in w for w in r["warnings"])
    assert not st.last_update["refit"]
    assert t_upd < t_build, "обновление должно быть быстрее полного построения"
    st2, r2 = update_forecast(st, rows[:3])
    assert st2.last_update["duplicates"] == 3


def test_event_paid_when_money_arrives():
    full = load_statement(base_df())
    cut = full["date"].max() - pd.Timedelta(days=5)
    st = build_state(full[full["date"] <= cut], [{"id": "inv", "type": "invoice", "direction": "in", "amount": 50000,
                                                   "date": (cut + pd.Timedelta(days=1)).date().isoformat(), "counterparty": "ООО «Новый»"}],
                     30, model="ets", **FAST)
    st, r = update_forecast(st, [{"date": (cut + pd.Timedelta(days=2)).strftime("%Y-%m-%d"), "amount": 50000,
                                  "direction": "in", "counterparty_name": "ООО «Новый»", "purpose": "Оплата по счету 1"}])
    assert st.events[0]["status"] == "paid"
