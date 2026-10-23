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
from .scenarios import run_scenarios as _run_scenarios
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
    try:
        state = df if isinstance(df, ForecastState) else build_state(df, events, horizon, **kwargs)
        return forecast_from_state(state, horizon, scenario)
    except Exception as exc:  # noqa: BLE001 — API ядра не должно падать
        return _safe_result(kwargs.get("company_id"), horizon, exc)


def _safe_result(company_id: Any, horizon: int, exc: Exception) -> dict[str, Any]:
    from datetime import datetime, timezone

    from .log import get_logger

    get_logger(__name__).error("forecast failed: %s", type(exc).__name__)
    return {"company_id": str(company_id or "unknown"),
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "horizon_days": int(horizon or 30), "as_of": None, "current_balance": None, "daily": [], "risks": [], "recurring": [], "sources_used": ["bank"],
            "warnings": [f"Прогноз не построен: внутренняя ошибка ({type(exc).__name__}). Проверьте формат выписки."]}


def run_scenarios(df: Any, events: list[dict[str, Any]] | None = None, scenario: dict[str, Any] | None = None,
                  **kwargs: Any) -> dict[str, Any]:
    """Базовый прогноз и прогноз по сценарию на одной оси + delta (ScenarioResult)."""
    try:
        return _run_scenarios(df, events, scenario, **kwargs)
    except Exception as exc:  # noqa: BLE001
        r = _safe_result(kwargs.get("company_id"), kwargs.get("horizon", 30), exc)
        return {"base": r, "scenario": r, "delta": {"first_gap_date": None, "max_shortfall": 0.0}}


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
