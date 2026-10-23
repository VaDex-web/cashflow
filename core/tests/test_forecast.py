"""Прогноз и риски: схема, тождество остатка, вероятности, воспроизводимость."""
from datetime import timedelta

import numpy as np

from cashflow_core import forecast, forecast_from_state
from cashflow_core.engine import Plan, PlannedItem, simulate
from helpers import FAST, base_df, base_state, last_date

KEYS = {"company_id", "generated_at", "horizon_days", "daily", "risks", "recurring", "sources_used", "warnings"}


def test_schema_matches_contract():
    r = forecast_from_state(base_state())
    assert KEYS <= set(r)
    assert len(r["daily"]) == 30 and r["horizon_days"] == 30
    for d in r["daily"]:
        assert d["balance_low"] <= d["balance_p50"] <= d["balance_high"]
    for k in r["risks"]:
        assert 0 <= k["probability"] <= 1
        assert k["severity"] in ("low", "medium", "high")
        assert k["reason"] and 1 <= len(k["recommendations"]) <= 3


def test_balance_equals_start_plus_flows():
    st = base_state()
    H = 10
    items = [PlannedItem(id="a", day=2, direction="in", amount=1000, category="revenue", kind="event", name="x", cv=0),
             PlannedItem(id="b", day=5, direction="out", amount=300, category="rent", kind="event", name="y", cv=0)]
    plan = Plan(start=st.as_of + timedelta(days=1), horizon=H, start_balance=5000.0, items=items,
                res_in=np.full(H, 10.0), res_out=np.full(H, 4.0), in_mult=np.ones(H), out_mult=np.ones(H),
                extra=np.zeros(H))
    st2 = type(st)(**{**st.__dict__, "err_in": np.zeros((0, H)), "err_out": np.zeros((0, H)), "err_scale": 0.0})
    bal = simulate(st2, plan, n_sims=50).balances
    expected = 5000 + np.cumsum(np.array([6.0] * H) + np.array([0, 0, 1000, 0, 0, -300, 0, 0, 0, 0]))
    assert np.allclose(bal, expected[None, :])


def test_planted_gap_detected_with_reason():
    df = base_df()
    d = (last_date(df) + timedelta(days=12)).date()
    ev = [{"id": "big", "type": "manual", "direction": "out", "amount": 3e7, "date": d.isoformat(), "note": "покупка оборудования"}]
    r = forecast(df, ev, 30, **FAST, model="ets")
    gap = [k for k in r["risks"] if k["date"] == d.isoformat()]
    assert gap and gap[0]["probability"] > 0.95 and gap[0]["severity"] == "high"
    assert "покупка оборудования" in gap[0]["reason"]
    assert gap[0]["shortfall_amount"] > 0
    assert any("big" in p.get("events", []) for p in r["daily"])


def test_reproducible_with_seed():
    a = forecast(base_df(), [], 30, **FAST, model="ets")
    b = forecast(base_df(), [], 30, **FAST, model="ets")
    assert a["daily"] == b["daily"] and a["risks"] == b["risks"]


def test_long_horizon():
    r = forecast_from_state(base_state(), horizon=60)
    assert len(r["daily"]) == 60
