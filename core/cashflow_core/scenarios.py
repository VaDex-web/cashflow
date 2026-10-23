"""Сценарии «что если» (п.7 задания).

Сценарий меняет план (расписание платежей и множители остаточных потоков),
а симуляция идёт с теми же случайными числами, что и база, поэтому разница
между base и scenario вызвана только сценарием.

* ``client_delay`` {counterparty_or_event_id, weeks: 2..4} — входящие платежи
  клиента (событие по id, регулярный паттерн или доля клиента в остаточной
  выручке) сдвигаются на N недель;
* ``revenue_drop`` {percent: 10..30} — вся выручка × (1 − p);
* ``unplanned_expense`` {amount, date} — разовый расход;
* ``fixed_cost_growth`` {percent} — зарплата, аренда, коммунальные, комиссии × (1 + p).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from .fmt import rub
from .schema import FIXED_COST_CATEGORIES, SCENARIO_TYPES

if TYPE_CHECKING:
    from .engine import ForecastState, Plan


def _num(x: Any, default: float) -> float:
    try:
        v = float(x)
        return v if np.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def apply_scenario(state: "ForecastState", plan: "Plan", scenario: dict[str, Any]) -> "Plan":
    """Вернуть копию плана с применённым сценарием (исходный план не меняется)."""
    from .engine import PlannedItem

    pl = plan.copy()
    stype = str((scenario or {}).get("type", ""))
    params = dict((scenario or {}).get("params") or {})
    H = pl.horizon
    if stype not in SCENARIO_TYPES:
        pl.warnings.append(f"Неизвестный сценарий «{stype}» — показан базовый прогноз.")
        return pl

    if stype == "client_delay":
        weeks = int(round(_num(params.get("weeks"), 2)))
        if not 1 <= weeks <= 12:
            pl.warnings.append("weeks вне диапазона 1–12 — использовано 2 недели.")
            weeks = 2
        shift = weeks * 7
        target = str(params.get("counterparty_or_event_id") or "").strip().lower()
        hits = 0
        for it in pl.items:
            if it.direction != "in" or not target:
                continue
            if target in (it.ref.lower(), it.id.lower()) or (it.counterparty and (target in it.counterparty.lower()
                                                                                    or it.counterparty.lower() in target)):
                it.day_shift += shift
                hits += 1
        # клиент без регулярного паттерна: сдвигаем его долю в остаточной выручке
        tx = state.df
        if target and len(tx):
            m = (tx["direction"] == "in") & (tx["counterparty_name"].str.lower().str.contains(target, regex=False)
                                              | (tx["counterparty_inn"].str.lower() == target))
            recent = pd.to_datetime(tx["date"]) > pd.Timestamp(state.as_of) - pd.Timedelta(days=90)
            rec_in = tx[(tx["direction"] == "in") & recent & ~tx["tx_id"].isin({t for p in state.patterns for t in p.tx_ids})]
            share = float(tx.loc[m & recent & tx.index.isin(rec_in.index), "amount"].sum() / max(rec_in["amount"].sum(), 1.0))
            if share > 0:
                hits += 1
                d = min(shift, H)
                delayed = pl.res_in[:d] * share
                pl.in_mult[:d] *= (1 - share)
                if shift < H:
                    pl.extra[shift] += float(delayed.sum())
        if not hits:
            pl.warnings.append("Сценарий задержки: такой клиент или событие не найдены — прогноз не изменился.")

    elif stype == "revenue_drop":
        pct = float(np.clip(_num(params.get("percent"), 20), 0, 100)) / 100
        for it in pl.items:
            if it.direction == "in" and it.category == "revenue":
                it.amount_mult *= (1 - pct)
        pl.in_mult *= (1 - pct)

    elif stype == "unplanned_expense":
        amount = abs(_num(params.get("amount"), 0.0))
        d = pd.to_datetime(params.get("date"), errors="coerce")
        day = 0 if pd.isna(d) else (d.date() - pl.start).days
        if amount <= 0:
            pl.warnings.append("Сценарий непредвиденного расхода: сумма не задана.")
        elif day >= H:
            pl.warnings.append("Дата непредвиденного расхода за горизонтом прогноза.")
        else:
            pl.items.append(PlannedItem(
                id=f"scn:expense:{amount}:{day}", day=max(0, day), direction="out", amount=amount, category="other",
                kind="event", name="непредвиденный расход", cv=0.0, movable=False, ref="scenario"))

    elif stype == "fixed_cost_growth":
        pct = float(np.clip(_num(params.get("percent"), 10), -50, 200)) / 100
        for it in pl.items:
            if it.direction == "out" and it.category in FIXED_COST_CATEGORIES:
                it.amount_mult *= (1 + pct)
    return pl


def run_scenarios(df: Any, events: list[dict[str, Any]] | None = None, scenario: dict[str, Any] | None = None,
                  **kwargs: Any) -> dict[str, Any]:
    """Базовый прогноз и прогноз по сценарию на одной оси + delta.

    Args:
        df: выписка или готовое :class:`engine.ForecastState`.
        events: события (игнорируются, если передано состояние).
        scenario: ``{type, params}`` по контракту.

    Returns:
        ``{base, scenario, delta}``. ``delta.first_gap_date`` и ``delta.max_shortfall`` —
        значения для сценария; дополнительно ``first_gap_date_base``,
        ``max_shortfall_base``, ``days_earlier`` (на сколько дней раньше наступает разрыв)
        и ``max_shortfall_change``.
    """
    from .engine import ForecastState, build_plan, build_state, ensure_error_horizon, make_result, simulate
    from .risk import gap_summary

    state = df if isinstance(df, ForecastState) else build_state(df, events, **kwargs)
    H = int(kwargs.get("horizon") or state.settings["horizon"])
    ensure_error_horizon(state, H)
    base_plan = build_plan(state, H)
    scn_plan = apply_scenario(state, base_plan, scenario or {})
    base_sim, scn_sim = simulate(state, base_plan), simulate(state, scn_plan)
    thr = float(state.settings.get("threshold", 0.0))
    gb, gs = gap_summary(base_plan, base_sim, thr), gap_summary(scn_plan, scn_sim, thr)
    days_earlier = None
    if gs["first_gap_day"] is not None:
        days_earlier = (gb["first_gap_day"] if gb["first_gap_day"] is not None else H) - gs["first_gap_day"]
    delta = {
        "first_gap_date": gs["first_gap_date"],
        "max_shortfall": gs["max_shortfall"],
        "first_gap_date_base": gb["first_gap_date"],
        "max_shortfall_base": gb["max_shortfall"],
        "days_earlier": days_earlier,
        "max_shortfall_change": round(gs["max_shortfall"] - gb["max_shortfall"], 2),
    }
    return {"base": make_result(state, base_plan, base_sim), "scenario": make_result(state, scn_plan, scn_sim),
            "delta": delta}
