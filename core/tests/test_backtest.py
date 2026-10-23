"""Бэктест: метрики считаются и имеют смысл."""
from cashflow_core import compare_models
from cashflow_core.backtest import backtest
from datagen import generate_statement


def test_backtest_small():
    res = backtest(generate_statement(days=330), n_origins=2, step=30, n_sims=200, models=("naive", "ets", "hybrid_ets"),
                   recurring_check=True)
    m = res["metrics"]
    for k in ("naive", "ets", "hybrid_ets"):
        assert m[k]["n_forecasts"] == 2
        assert 0 <= m[k]["coverage_p10_p90"] <= 1
        assert m[k]["balance_mae_rub"] >= 0
    assert m["_recurring"]["hit_rate_pm3d"] > 0.7
    tab = compare_models(res)
    assert list(tab.index) == ["ets", "hybrid_ets", "naive"]
