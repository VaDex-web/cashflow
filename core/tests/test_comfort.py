"""Подушка безопасности: риск «мало денег» отдельно от кассового разрыва."""
from datetime import timedelta

from cashflow_core import build_state, forecast_from_state, load_statement
from helpers import FAST, base_df, last_date


def _state(**kw):
    df = base_df()
    bal = float(load_statement(df)["balance_eod"].iloc[-1])
    d = (last_date(df) + timedelta(days=10)).date().isoformat()
    # большой платёж оставляет на счёте плюс, но меньше подушки
    ev = [{"id": "big", "type": "manual", "direction": "out", "amount": bal * 0.97, "date": d,
           "source": "manual", "note": "ремонт"}]
    return build_state(df, ev, 30, model="ets", **FAST, **kw)


def test_default_comfort_is_seven_days_of_expenses():
    st = _state()
    assert st.settings["comfort_source"] == "auto" and st.settings["comfort_balance"] > 0
    r = forecast_from_state(st)
    assert r["comfort_balance"] == st.settings["comfort_balance"]


def test_below_comfort_risk_and_user_value():
    st = _state(comfort_balance=10_000_000_000)  # заведомо огромная подушка
    r = forecast_from_state(st)
    assert any("подушки безопасности" in k["reason"] for k in r["risks"])
    st0 = _state(comfort_balance=0)
    r0 = forecast_from_state(st0)
    assert not any("подушки безопасности" in k["reason"] for k in r0["risks"])


def test_sources_shown_in_reason():
    df = base_df()
    d = (last_date(df) + timedelta(days=8)).date().isoformat()
    ev = [{"id": "x", "type": "manual", "direction": "out", "amount": 5e7, "date": d, "source": "manual", "note": "оборудование"}]
    r = forecast_from_state(build_state(df, ev, 30, model="ets", **FAST))
    gap = [k for k in r["risks"] if k["date"] == d][0]
    assert "вы ввели" in gap["reason"]
    assert all(t.startswith("Можно") or t.startswith("Если") or t.startswith("Счёт") for t in gap["recommendations"])
