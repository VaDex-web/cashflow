"""cashflow_core — ядро прогноза остатка и кассовых разрывов для малого бизнеса.

Публичный интерфейс (контракт docs/contract.md):

>>> from cashflow_core import load_statement, categorize, detect_recurring, forecast
>>> df = load_statement("data/raw/statements/C001.csv")
>>> result = forecast(df, events=[], horizon=30)

Все функции возвращают JSON-совместимые dict/list и не бросают исключений
на «грязных» данных: проблемы описываются в поле ``warnings``.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from .categorize import categorize, evaluate_categorization
from .engine import ForecastState, build_state, forecast_from_state
from .io import load_statement, read_companies, to_daily
from .recurring import detect_recurring
from .scenarios import run_scenarios
from .taxes import estimate_tax_regime

__all__ = [
    "load_statement", "read_companies", "to_daily", "categorize", "evaluate_categorization", "detect_recurring",
    "forecast", "run_scenarios", "update_forecast", "backtest", "compare_models", "build_state",
    "forecast_from_state", "estimate_tax_regime", "ForecastState",
]
__version__ = "0.1.0"


def forecast(df: Any, events: list[dict[str, Any]] | None = None, horizon: int = 30,
             scenario: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    """Прогноз остатка по дням, риски разрывов и регулярные платежи (ForecastResult).

    Args:
        df: выписка (путь, DataFrame, результат :func:`load_statement`) или :class:`ForecastState`.
        events: ожидаемые события (Event из контракта).
        horizon: горизонт в днях (≥ 30 рекомендуется).
        scenario: необязательный сценарий {type, params}.
        **kwargs: company_id, n_sims (2000), seed (42), threshold (0), model ("auto"), as_of.
    """
    state = df if isinstance(df, ForecastState) else build_state(df, events, horizon, **kwargs)
    return forecast_from_state(state, horizon, scenario)


def update_forecast(state: ForecastState, new_rows: Any) -> tuple[ForecastState, dict[str, Any]]:
    """Инкрементальное обновление прогноза новыми операциями (без полного пересчёта)."""
    from .incremental import update_forecast as _upd

    return _upd(state, new_rows)


def backtest(df: Any, **kwargs: Any) -> dict[str, Any]:
    """Rolling-origin бэктест (метрики остатка, потоков, интервалов и разрывов)."""
    from .backtest import backtest as _bt

    return _bt(df, **kwargs)


def compare_models(df: Any, **kwargs: Any) -> pd.DataFrame:
    """Таблица метрик для сравнения подходов (naive / ets / hybrid)."""
    from .backtest import compare_models as _cm

    return _cm(df, **kwargs)
