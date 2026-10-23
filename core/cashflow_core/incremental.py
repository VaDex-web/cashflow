"""Инкрементальное обновление прогноза (п.8 задания).

При поступлении новых операций полный пересчёт не делается:

1. новые строки чистятся тем же парсером и размечаются **уже обученным** категоризатором;
2. дубли уже известных операций отбрасываются;
3. остаток сдвигается (по ``balance_eod`` новых строк или «старый остаток + потоки»);
4. операции сопоставляются с ожидаемыми регулярными платежами (расписание сдвигается)
   и с событиями (статус → ``paid``); неоплаченные в срок события → ``overdue``;
5. остаточные ряды продлеваются; модели потоков **не переобучаются** — они берут
   продлённую историю как контекст, поэтому пересчитывается только хвост прогноза;
6. полная перестройка состояния — только если с последнего обучения прошло
   больше ``REFIT_DAYS`` дней.
"""
from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from .engine import RESCUE_INFLOW_CATEGORIES, ForecastState, build_plan, build_state, ensure_error_horizon, make_result, simulate
from .fmt import day_month, rub
from .io import load_statement
from .log import get_logger
from .recurring import AGGREGATE_CATEGORIES, _cp_key

log = get_logger(__name__)

REFIT_DAYS = 30
_KEY = ["date", "amount", "direction", "counterparty_inn", "counterparty_name", "purpose"]


def _to_frame(new_rows: Any) -> pd.DataFrame:
    if isinstance(new_rows, pd.DataFrame):
        return new_rows.copy()
    if isinstance(new_rows, dict):
        return pd.DataFrame([new_rows])
    if isinstance(new_rows, (list, tuple)):
        return pd.DataFrame(list(new_rows))
    return load_statement(new_rows)  # путь к файлу


def _match_event(e: dict[str, Any], row: pd.Series) -> bool:
    if row["direction"] != e["direction"]:
        return False
    cp = (e.get("counterparty") or "").lower()
    tol = 0.1 if cp else 0.01  # без контрагента — только почти точное совпадение суммы
    if not (1 - tol <= row["amount"] / max(e["amount"], 1.0) <= 1 + tol):
        return False
    d = row["date"].date() if hasattr(row["date"], "date") else row["date"]
    ed = date.fromisoformat(e["date"])
    if not (ed - timedelta(days=10) <= d <= ed + timedelta(days=45)):
        return False
    return not cp or cp in str(row["counterparty_name"]).lower() or cp == str(row["counterparty_inn"])


def update_forecast(state: ForecastState, new_rows: Any) -> tuple[ForecastState, dict[str, Any]]:
    """Добавить новые операции и пересчитать прогноз без полного переобучения.

    Args:
        state: состояние из :func:`engine.build_state` (изменяется на месте и возвращается).
        new_rows: список dict / DataFrame / путь к CSV с новыми операциями (формат выписки).

    Returns:
        (state, ForecastResult). В ``state.last_update`` — что изменилось
        (сколько строк принято, какие события оплачены/просрочены, был ли полный пересчёт).
    """
    t0 = time.time()
    notes: list[str] = []
    raw = _to_frame(new_rows)
    if isinstance(new_rows, (str, bytes)) or ("tx_id" in raw.columns and "signed_amount" in raw.columns):
        new = raw
    else:
        new = load_statement(raw, opening_balance=state.start_balance)
    new = new.copy()
    new.attrs = {}
    info: dict[str, Any] = {"rows_received": int(len(raw)), "rows_accepted": 0, "duplicates": 0,
                            "events_paid": [], "events_overdue": [], "patterns_matched": 0, "refit": False}
    if not len(new):
        state.last_update = info
        return state, _result(state, ["Новых операций не найдено."])

    old = state.df
    old_keys = set(map(tuple, old[_KEY].astype(str).values))
    is_dup = [tuple(r) in old_keys for r in new[_KEY].astype(str).values]
    info["duplicates"] = int(sum(is_dup))
    new = new[~np.array(is_dup, dtype=bool)].reset_index(drop=True)
    if not len(new):
        state.last_update = info
        return state, _result(state, ["Все переданные операции уже есть в выписке."])
    if state.categorizer is not None:
        new = state.categorizer.transform(new)
    else:
        new["category"], new["category_label"], new["category_confidence"], new["category_source"] = "other", "Прочее", 0.3, "default"
    new["tx_id"] = [f"u{abs(hash((t, i, time.time()))) % 10**12:012d}" for i, t in enumerate(new["tx_id"])]
    info["rows_accepted"] = int(len(new))

    # --- остаток и дневной ряд
    new_dates = pd.to_datetime(new["date"])
    new_end = max(new_dates.max().date(), state.as_of)
    net_new = float(new["signed_amount"].sum())
    if new["balance_eod"].notna().any() and new_dates[new["balance_eod"].notna()].max().date() >= state.as_of:
        last_day = new_dates[new["balance_eod"].notna()].max()
        state.start_balance = float(new.loc[new_dates == last_day, "balance_eod"].dropna().iloc[-1])
    else:
        state.start_balance = float(state.start_balance + net_new)
    state.df = pd.concat([old, new], ignore_index=True)

    # --- регулярные платежи
    matched_ids: set[str] = set()
    new["cp"] = [_cp_key(i, n) for i, n in zip(new["counterparty_inn"], new["counterparty_name"])]
    for p in state.patterns:
        sched = p.schedule(new_end + timedelta(days=p.period_days))
        if not sched:
            continue
        exp = sched[0][1]
        tol = 5 if p.kind in ("monthly", "quarterly") else 2
        cand = new[(new["direction"] == p.direction) & (new["category"] == p.category)]
        if not p.group_key.startswith("cat:"):
            cand = cand[cand["cp"] == p.group_key]
        cand = cand[(pd.to_datetime(cand["date"]).dt.date >= exp - timedelta(days=20 if p.category in AGGREGATE_CATEGORIES else tol))
                    & (pd.to_datetime(cand["date"]).dt.date <= exp + timedelta(days=tol + 10))]
        if len(cand):
            d = pd.to_datetime(cand["date"]).dt.date.min()
            day = cand[pd.to_datetime(cand["date"]).dt.date == d]
            p.register_payment(d, float(day["amount"].sum()), "")
            p.tx_ids.extend(day["tx_id"].tolist())
            matched_ids |= set(day["tx_id"])
            info["patterns_matched"] += 1
        elif p.direction == "in" and (new_end - exp).days > 3:
            notes.append(f"Регулярное поступление «{p.name}» ожидалось {day_month(exp)}, но не пришло — "
                         f"в прогнозе оно сдвинуто и риск пересчитан.")

    # --- события
    for e in state.events:
        if e["status"] == "paid":
            continue
        hit = next((i for i, r in new.iterrows() if r["tx_id"] not in matched_ids and _match_event(e, r)), None)
        if hit is not None:
            e["status"] = "paid"
            matched_ids.add(new.at[hit, "tx_id"])
            info["events_paid"].append(e["id"])
        elif date.fromisoformat(e["date"]) < new_end - timedelta(days=2) and e["status"] == "expected":
            e["status"] = "overdue"
            info["events_overdue"].append(e["id"])
            what = "поступление" if e["direction"] == "in" else "платёж"
            notes.append(f"Ожидаемое {what} {rub(e['amount'])} ({e.get('counterparty') or e['type']}) на "
                         f"{day_month(date.fromisoformat(e['date']))} не прошло — помечено как просроченное.")

    # --- полный пересчёт, если накопилось много новых дней
    if state.fitted_as_of and (new_end - state.fitted_as_of).days >= REFIT_DAYS:
        settings = state.settings
        fresh = build_state(state.df, state.events, settings["horizon"], company_id=state.company_id,
                            model=settings.get("model", "auto"), n_sims=settings["n_sims"], seed=settings["seed"],
                            threshold=settings["threshold"])
        fresh.events = state.events
        info["refit"] = True
        info["secs"] = round(time.time() - t0, 3)
        fresh.last_update = info
        log.info("incremental update with refit: rows=%d", info["rows_accepted"])
        return fresh, _result(fresh, notes)

    # --- продлеваем дневной ряд и остаточные ряды (без переобучения моделей)
    idx = pd.date_range(state.daily.index[0], pd.Timestamp(new_end), freq="D", name="date")
    add = new[~new["tx_id"].isin(matched_ids)]
    add = add[~((add["direction"] == "in") & add["category"].isin(RESCUE_INFLOW_CATEGORIES))]
    if state.excluded_tax_from_residual:
        add = add[~((add["direction"] == "out") & (add["category"] == "taxes"))]
    ad = pd.to_datetime(add["date"])
    add_in = add[add["direction"] == "in"].groupby(ad[add["direction"] == "in"])["amount"].sum()
    add_out = add[add["direction"] == "out"].groupby(ad[add["direction"] == "out"])["amount"].sum()
    for name, addv in (("res_in", add_in), ("raw_in", add_in), ("res_out", add_out), ("raw_out", add_out)):
        s = getattr(state, name).reindex(idx).fillna(0.0)
        s = s.add(addv.reindex(idx).fillna(0.0), fill_value=0.0)
        setattr(state, name, s)
    daily = state.daily.reindex(idx)
    nd = new.groupby(pd.to_datetime(new["date"]))
    for col, ser in (("inflow", nd.apply(lambda x: x.loc[x["direction"] == "in", "amount"].sum(), include_groups=False)),
                     ("outflow", nd.apply(lambda x: x.loc[x["direction"] == "out", "amount"].sum(), include_groups=False))):
        daily[col] = daily[col].fillna(0.0).add(ser.reindex(idx).fillna(0.0), fill_value=0.0)
    daily["net"] = daily["inflow"] - daily["outflow"]
    daily["n_tx"] = daily["n_tx"].fillna(0).astype(int)
    daily["balance"] = daily["balance"].ffill()
    daily.loc[daily.index[-1], "balance"] = state.start_balance
    daily["balance_reported"] = daily["balance_reported"].ffill()
    daily["mismatch"] = daily["mismatch"].fillna(False).astype(bool)
    state.daily = daily
    state.as_of = new_end
    info["secs"] = round(time.time() - t0, 3)
    state.last_update = info
    log.info("incremental update: rows=%d matched=%d secs=%.3f", info["rows_accepted"], info["patterns_matched"],
             info["secs"])
    return state, _result(state, notes)


def _result(state: ForecastState, notes: list[str]) -> dict[str, Any]:
    H = int(state.settings["horizon"])
    ensure_error_horizon(state, H)
    plan = build_plan(state, H)
    return make_result(state, plan, simulate(state, plan), notes)
