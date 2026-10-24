import numpy as np
import pandas as pd

from cashflow_core import build_state, forecast_from_state, load_statement
from cashflow_core.backtest import backtest
from helpers import FAST, base_df


def test_future_rows_do_not_change_forecast():
    full = load_statement(base_df())
    origin = (full["date"].max() - pd.Timedelta(days=60)).date()
    spoiled = full.copy()
    fut = spoiled["date"].dt.date > origin
    spoiled.loc[fut, "amount"] *= 10
    spoiled.loc[fut, "balance_eod"] = -1e12
    spoiled.loc[fut, "purpose"] = "Перечисление заработной платы"
    spoiled["signed_amount"] = np.where(spoiled["direction"] == "in", spoiled["amount"], -spoiled["amount"])
    a = forecast_from_state(build_state(full, [], 30, as_of=origin, model="auto", **FAST))
    b = forecast_from_state(build_state(spoiled, [], 30, as_of=origin, model="auto", **FAST))
    assert a["daily"] == b["daily"]
    assert a["risks"] == b["risks"]
    assert a["recurring"] == b["recurring"]


def test_backtest_uses_only_past_balance():
    df = base_df()
    st_cut = (pd.to_datetime(df["date"]).max() - pd.Timedelta(days=31)).date()
    full = load_statement(df)
    st = build_state(full, [], 30, as_of=st_cut, model="ets", **FAST)
    last_known = full[full["date"].dt.date <= st_cut]["balance_eod"].dropna().iloc[-1]
    assert abs(st.start_balance - last_known) < 0.01
    assert st.as_of == st_cut
    assert pd.to_datetime(st.df["date"]).max().date() <= st_cut
    assert st.daily.index.max().date() <= st_cut


def test_backtest_runs_on_short_history():
    from datagen import generate_statement

    r = backtest(generate_statement(days=100), n_sims=100, models=("naive", "ets", "hybrid_ets"))
    assert r["origins"], "для короткой истории должна быть хотя бы одна отсечка"
