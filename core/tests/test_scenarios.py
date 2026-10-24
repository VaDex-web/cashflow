from datetime import timedelta

from cashflow_core import run_scenarios
from cashflow_core.engine import build_state
from cashflow_core.io import load_statement
from helpers import FAST, base_df, last_date


def _state_with_tight_balance():
    df = base_df()
    d = (last_date(df) + timedelta(days=20)).date()
    big = load_statement(df).iloc[-1]["balance_eod"]
    ev = [{"id": "pay", "type": "invoice", "direction": "out", "amount": float(big) * 1.3, "date": d.isoformat()},
          {"id": "client", "type": "invoice", "direction": "in", "amount": float(big) * 0.3,
           "date": (d - timedelta(days=3)).isoformat(), "counterparty": "ООО «Клиент-01»"}]
    return build_state(df, ev, 30, model="ets", **FAST)


def test_revenue_drop_makes_things_worse():
    r = run_scenarios(_state_with_tight_balance(), scenario={"type": "revenue_drop", "params": {"percent": 30}})
    assert r["delta"]["max_shortfall"] >= r["delta"]["max_shortfall_base"]
    if r["delta"]["first_gap_date_base"]:
        assert r["delta"]["first_gap_date"] <= r["delta"]["first_gap_date_base"]


def test_unplanned_expense_adds_its_amount():
    st = _state_with_tight_balance()
    r = run_scenarios(st, scenario={"type": "unplanned_expense", "params": {"amount": float(st.start_balance) * 2, "date": str(st.as_of + timedelta(days=2))}})
    assert r["delta"]["max_shortfall_change"] > 0
    assert len(r["base"]["daily"]) == len(r["scenario"]["daily"])
    assert r["base"]["daily"][0]["date"] == r["scenario"]["daily"][0]["date"]


def test_fixed_cost_growth_and_client_delay():
    st = _state_with_tight_balance()
    g = run_scenarios(st, scenario={"type": "fixed_cost_growth", "params": {"percent": 20}})
    assert g["delta"]["max_shortfall"] >= g["delta"]["max_shortfall_base"]
    c = run_scenarios(st, scenario={"type": "client_delay", "params": {"counterparty_or_event_id": "client", "weeks": 3}})
    assert c["delta"]["max_shortfall"] >= c["delta"]["max_shortfall_base"]


def test_unknown_scenario_is_safe():
    r = run_scenarios(_state_with_tight_balance(), scenario={"type": "nope", "params": {}})
    assert r["delta"]["max_shortfall_change"] == 0
    assert any("Неизвестный сценарий" in w for w in r["scenario"]["warnings"])


def _end_p50(r, key):
    return r[key]["daily"][-1]["balance_p50"]


def test_client_lost_removes_its_payments():
    st = _state_with_tight_balance()
    r = run_scenarios(st, scenario={"type": "client_lost", "params": {"counterparty_or_event_id": "ООО «Клиент-01»"}})
    assert r["delta"]["max_shortfall"] >= r["delta"]["max_shortfall_base"]
    assert _end_p50(r, "scenario") < _end_p50(r, "base")
    nobody = run_scenarios(st, scenario={"type": "client_lost", "params": {"counterparty_or_event_id": "ООО «Нет такого»"}})
    assert any("не найден" in w for w in nobody["scenario"]["warnings"])


def test_tax_increase_lowers_balance_by_tax_share():
    st = _state_with_tight_balance()
    r = run_scenarios(st, scenario={"type": "tax_increase", "params": {"percent": 50}})
    assert _end_p50(r, "scenario") < _end_p50(r, "base")
    assert r["delta"]["max_shortfall"] >= r["delta"]["max_shortfall_base"]
