"""Честная проверка качества: rolling-origin бэктест (п.6 задания).

Для каждой даты отсечения ``o`` модель видит только операции до ``o`` включительно
(категоризатор, регулярные платежи, налоги и модели потоков обучаются заново),
прогнозирует 30 дней и сравнивается с фактом.

Подходы:

* ``naive`` — повтор последних 28 дней поступлений и списаний;
* ``ets`` — сезонный профиль (уровень × тип дня × «как год назад») по всем потокам;
* ``hybrid`` — регулярные платежи + налоговая модель + остаточные потоки (ETS/бустинг,
  выбор по прошлым ошибкам) + Monte Carlo. Это продуктовая модель.

Интервалы у всех подходов строятся одинаково — по эмпирическим ошибкам прошлых
прогнозов, — чтобы сравнение было честным.

Разрыв для метрик precision/recall считается по остатку **без «спасательных»
поступлений** (пополнения собственными средствами, займы учредителя, транши):
в данных владелец часто закрывает дыру сам, и по фактическому остатку разрыва
«не было», хотя деньги кончились. Отсечки, где остаток уже отрицательный,
в метрики разрывов не входят (там предупреждать уже поздно).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .engine import RESCUE_INFLOW_CATEGORIES, build_plan, build_state, simulate
from .flows import MODEL_FACTORIES, error_paths
from .io import load_statement, to_daily
from .log import get_logger
from .schema import GAP_PROBABILITY_LIKELY, INTERVAL_HIGH_Q, INTERVAL_LOW_Q

log = get_logger(__name__)

DEFAULT_MODELS = ("naive", "ets", "hybrid")


@dataclass
class OriginForecast:
    balances: np.ndarray       # (n_sims, H)
    exp_in: np.ndarray         # ожидаемые дневные поступления
    exp_out: np.ndarray


def _baseline(daily_hist: pd.DataFrame, name: str, H: int, n_sims: int, seed: int, b0: float,
              rescue_hist: pd.Series | None = None) -> OriginForecast:
    y_in, y_out = daily_hist["inflow"].astype(float), daily_hist["outflow"].astype(float)
    if rescue_hist is not None:
        y_in = (y_in - rescue_hist.reindex(y_in.index).fillna(0.0)).clip(lower=0.0)
    m_in, m_out = MODEL_FACTORIES[name](seed).fit(y_in), MODEL_FACTORIES[name](seed).fit(y_out)
    p_in, p_out = m_in.forecast(y_in, H), m_out.forecast(y_out, H)
    e_in, _ = error_paths(y_in, name, H, seed=seed)
    e_out, _ = error_paths(y_out, name, H, seed=seed)
    rng = np.random.default_rng([seed, 0])
    if len(e_in) >= 5:
        pick = rng.integers(0, len(e_in), n_sims)
        net = p_in - p_out + e_in[pick] - e_out[pick]
    else:
        sd = float((y_in - y_out).std() or 0.0)
        net = p_in - p_out + 1.5 * sd * rng.standard_normal((n_sims, H))
    return OriginForecast(b0 + np.cumsum(net, axis=1), p_in, p_out)


def _hybrid(tx: pd.DataFrame, origin: date, H: int, n_sims: int, seed: int, model: str,
            interval_scale: float = 1.0) -> OriginForecast:
    st = build_state(tx, [], H, as_of=origin, n_sims=n_sims, seed=seed, model=model, interval_scale=interval_scale)
    plan = build_plan(st, H)
    sim = simulate(st, plan)
    return OriginForecast(sim.balances, sim.det_in + plan.res_in, sim.det_out + plan.res_out)


def _actual(daily: pd.DataFrame, tx: pd.DataFrame, origin: date, H: int) -> dict[str, np.ndarray]:
    o = pd.Timestamp(origin)
    idx = pd.date_range(o + pd.Timedelta(days=1), periods=H, freq="D")
    bal_col = daily["balance_reported"].where(daily["balance_reported"].notna(), daily["balance"])
    bal = bal_col.reindex(idx).ffill().values
    rescue = tx[(tx["direction"] == "in") & tx["category"].isin(RESCUE_INFLOW_CATEGORIES)]
    r = rescue.groupby(pd.to_datetime(rescue["date"]))["amount"].sum().reindex(idx).fillna(0.0).values
    return {
        "balance": bal,
        "need": bal - np.cumsum(r),
        "inflow": daily["inflow"].reindex(idx).fillna(0.0).values - r,
        "outflow": daily["outflow"].reindex(idx).fillna(0.0).values,
        "b0": float(bal_col.loc[:o].iloc[-1]),
    }


def _origins(daily: pd.DataFrame, H: int, n_origins: int, step: int, min_train: int) -> list[date]:
    last = daily.index[-1] - pd.Timedelta(days=H)
    first_ok = daily.index[0] + pd.Timedelta(days=min_train)
    out = []
    for j in range(n_origins):
        o = last - pd.Timedelta(days=step * j)
        if o < first_ok:
            break
        out.append(o.date())
    return sorted(out)


def _recurring_hits(tx: pd.DataFrame, origin: date, H: int, seed: int) -> dict[str, float]:
    """Точность расписания регулярных платежей: пришёл ли платёж группы в ±3 дня от ожидаемой даты."""
    from .categorize import fit_categorizer
    from .recurring import _cp_key, find_patterns

    hist = tx[pd.to_datetime(tx["date"]).dt.date <= origin]
    fut = tx[(pd.to_datetime(tx["date"]).dt.date > origin)
             & (pd.to_datetime(tx["date"]).dt.date <= origin + timedelta(days=H + 3))]
    if len(hist) < 30:
        return {"n": 0}
    cz = fit_categorizer(hist, seed=seed)
    hist_c = cz.transform(hist)
    fut_c = cz.transform(fut)
    fut_c["d"] = pd.to_datetime(fut_c["date"]).dt.date
    fut_c["cp"] = [_cp_key(i, n) for i, n in zip(fut_c["counterparty_inn"], fut_c["counterparty_name"])]
    pats = find_patterns(hist_c, origin)
    n = hits = 0
    amt_err = []
    for p in pats:
        for _, exp in p.schedule(origin + timedelta(days=H)):
            if exp <= origin:
                continue
            n += 1
            g = fut_c[(fut_c["direction"] == p.direction) & (fut_c["category"] == p.category)]
            if p.group_key.startswith(("inn:", "name:")):
                g = g[g["cp"] == p.group_key]
            near = g[(g["d"] >= exp - timedelta(days=3)) & (g["d"] <= exp + timedelta(days=3))]
            if len(near):
                hits += 1
                day_sum = near.groupby("d")["amount"].sum()
                act = float(day_sum.iloc[(np.abs([(x - exp).days for x in day_sum.index])).argmin()])
                amt_err.append(abs(act - p.amount_forecast) / max(act, 1.0))
    return {"n": n, "hits": hits, "amount_ape": amt_err}


def backtest(df: Any, *, horizon: int = 30, n_origins: int = 8, step: int = 21, min_train: int = 180,
             models: Iterable[str] = DEFAULT_MODELS, n_sims: int = 500, seed: int = 42, threshold: float = 0.0,
             company_id: str | None = None, hybrid_model: str = "auto", recurring_check: bool = True) -> dict[str, Any]:
    """Rolling-origin бэктест одной компании.

    Returns:
        ``{"company_id", "origins": [...], "records": {model: [запись по отсечке]}, "recurring": {...},
        "metrics": {model: агрегаты}}``. Запись по отсечке содержит ошибки по дням и разрывы —
        из них :func:`aggregate` считает метрики по многим компаниям.
    """
    tx = df if isinstance(df, pd.DataFrame) and "tx_id" in df.columns else load_statement(df, company_id=company_id)
    cid = str(company_id or tx.attrs.get("company_id") or "unknown")
    tx = tx.copy()
    tx.attrs = {}
    from .categorize import categorize

    tx_cat = categorize(tx)  # только для «спасательных» поступлений в факте (не в модели)
    daily = to_daily(tx)
    resc = tx_cat[(tx_cat["direction"] == "in") & tx_cat["category"].isin(RESCUE_INFLOW_CATEGORIES)]
    rescue_daily = resc.groupby(pd.to_datetime(resc["date"]))["amount"].sum()
    H = int(horizon)
    origins = _origins(daily, H, n_origins, step, min_train)
    records: dict[str, list[dict[str, Any]]] = {m: [] for m in models}
    rec_stats = {"n": 0, "hits": 0, "amount_ape": []}
    for o in origins:
        act = _actual(daily, tx_cat, o, H)
        turnover = float(daily.loc[:pd.Timestamp(o)].iloc[-30:]["outflow"].sum()) or 1.0
        for m in models:
            t0 = time.time()
            try:
                # бэктест меряет «сырую» модель (масштаб 1.0); калибровка оценивается отдельно
                if m == "hybrid":
                    fc = _hybrid(tx, o, H, n_sims, seed, hybrid_model)
                elif m.startswith("hybrid_"):
                    fc = _hybrid(tx, o, H, n_sims, seed, m.split("_", 1)[1])
                else:
                    fc = _baseline(daily.loc[:pd.Timestamp(o)], m, H, n_sims, seed, act["b0"], rescue_daily)
            except Exception as exc:  # noqa: BLE001
                log.warning("backtest model failed: %s %s", m, type(exc).__name__)
                continue
            q = np.quantile(fc.balances, [INTERVAL_LOW_Q, 0.5, INTERVAL_HIGH_Q], axis=0)
            p_gap = (fc.balances < threshold).mean(axis=0)
            target = act["need"]  # все модели прогнозируют остаток без «спасательных» пополнений
            records[m].append({
                "origin": o.isoformat(), "b0": act["b0"], "turnover30": turnover,
                "err": (q[1] - target).tolist(),
                "err_vs_actual": (q[1] - act["balance"]).tolist(),
                "abs_actual": np.abs(target).tolist(),
                "covered": ((target >= q[0]) & (target <= q[2])).tolist(),
                "width": (q[2] - q[0]).tolist(),
                "lo_off": (q[1] - q[0]).tolist(), "hi_off": (q[2] - q[1]).tolist(),
                "in_err": (fc.exp_in - act["inflow"]).tolist(), "in_act": act["inflow"].tolist(),
                "out_err": (fc.exp_out - act["outflow"]).tolist(), "out_act": act["outflow"].tolist(),
                "p_gap": p_gap.tolist(),
                "gap_need": (act["need"] < threshold).tolist(),
                "gap_actual": (act["balance"] < threshold).tolist(),
                "secs": round(time.time() - t0, 2),
            })
        if recurring_check:
            try:
                r = _recurring_hits(tx, o, H, seed)
                if r.get("n"):
                    rec_stats["n"] += r["n"]
                    rec_stats["hits"] += r["hits"]
                    rec_stats["amount_ape"] += r["amount_ape"]
            except Exception as exc:  # noqa: BLE001
                log.warning("recurring check failed: %s", type(exc).__name__)
    out = {"company_id": cid, "origins": [o.isoformat() for o in origins], "records": records, "recurring": rec_stats}
    out["metrics"] = aggregate([out])
    return out


# --------------------------------------------------------------------------- aggregation
def _gap_metrics(recs: list[dict[str, Any]], key: str) -> dict[str, Any]:
    tp = fp = fn = tn = 0
    leads, date_err, brier = [], [], []
    for r in recs:
        if r["b0"] < 0:
            continue  # уже в минусе — предупреждать поздно, в метрики не берём
        act = np.array(r[key], dtype=bool)
        p = np.array(r["p_gap"])
        pred = p >= GAP_PROBABILITY_LIKELY
        brier.append(float(np.mean((p - act) ** 2)))
        a, b = act.any(), pred.any()
        if a and b:
            tp += 1
            fa, fb = int(np.argmax(act)), int(np.argmax(pred))
            leads.append(fa + 1)
            date_err.append(abs(fa - fb))
        elif b:
            fp += 1
        elif a:
            fn += 1
        else:
            tn += 1
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    f1 = 2 * prec * rec / (prec + rec) if prec and rec else None
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(prec, 3) if prec is not None else None,
            "recall": round(rec, 3) if rec is not None else None,
            "f1": round(f1, 3) if f1 is not None else None,
            "lead_days_mean": round(float(np.mean(leads)), 1) if leads else None,
            "lead_days_median": float(np.median(leads)) if leads else None,
            "date_error_days_median": float(np.median(date_err)) if date_err else None,
            "brier": round(float(np.mean(brier)), 4) if brier else None}


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Свести записи бэктеста по многим компаниям в метрики по моделям."""
    models = sorted({m for r in results for m in r["records"]})
    out: dict[str, Any] = {}
    for m in models:
        recs = [x for r in results for x in r["records"].get(m, [])]
        if not recs:
            continue
        err = np.array([x["err"] for x in recs])
        absact = np.array([x["abs_actual"] for x in recs])
        turn = np.array([x["turnover30"] for x in recs])[:, None]
        rel = np.abs(err) / turn
        cov = np.array([x["covered"] for x in recs], dtype=float)
        in_e, in_a = np.array([x["in_err"] for x in recs]), np.array([x["in_act"] for x in recs])
        out_e, out_a = np.array([x["out_err"] for x in recs]), np.array([x["out_act"] for x in recs])
        H = err.shape[1]
        wk = H // 7 * 7

        def weekly_wape(e: np.ndarray, a: np.ndarray) -> float:
            ew = np.abs(e[:, :wk].reshape(len(e), -1, 7).sum(axis=2)).sum()
            aw = np.abs(a[:, :wk].reshape(len(a), -1, 7).sum(axis=2)).sum()
            return float(ew / aw) if aw else float("nan")

        out[m] = {
            "n_forecasts": len(recs),
            "balance_mae_rub": round(float(np.abs(err).mean()), 0),
            "balance_wape": round(float(np.abs(err).sum() / max(absact.sum(), 1.0)), 4),
            "balance_mae_pct_turnover": round(float(np.median(rel.mean(axis=1))), 4),
            "balance_mae_pct_turnover_by_h": [round(float(np.median(rel[:, h])), 4) for h in range(H)],
            "balance_mae_pct_turnover_h7_h14_h30": [round(float(np.median(rel[:, h])), 4) for h in (6, 13, H - 1)],
            "inflow_wape_daily": round(float(np.abs(in_e).sum() / max(in_a.sum(), 1.0)), 4),
            "outflow_wape_daily": round(float(np.abs(out_e).sum() / max(out_a.sum(), 1.0)), 4),
            "inflow_wape_weekly": round(weekly_wape(in_e, in_a), 4),
            "outflow_wape_weekly": round(weekly_wape(out_e, out_a), 4),
            "coverage_p10_p90": round(float(cov.mean()), 4),
            "coverage_nominal": INTERVAL_HIGH_Q - INTERVAL_LOW_Q,
            "gaps_without_owner_rescue": _gap_metrics(recs, "gap_need"),
            "gaps_actual_balance": _gap_metrics(recs, "gap_actual"),
            "secs_per_forecast": round(float(np.mean([x["secs"] for x in recs])), 2),
        }
    rs = [r["recurring"] for r in results if r.get("recurring", {}).get("n")]
    if rs:
        n = sum(r["n"] for r in rs)
        hits = sum(r["hits"] for r in rs)
        ape = [a for r in rs for a in r["amount_ape"]]
        out["_recurring"] = {"expected_payments": n, "hit_rate_pm3d": round(hits / n, 4) if n else None,
                             "amount_mape_median": round(float(np.median(ape)), 4) if ape else None}
    return out


def calibrate_interval_scale(results: list[dict[str, Any]], model: str = "hybrid", target: float = 0.8,
                             grid: Iterable[float] = tuple(np.round(np.arange(0.8, 3.01, 0.05), 2))) -> dict[str, Any]:
    """Подобрать множитель ширины интервала на РАННИХ отсечках каждой компании и проверить на ПОЗДНИХ.

    Интервал после калибровки: [p50 − k·(p50 − P10), p50 + k·(P90 − p50)]. Если в записях нет
    отдельных границ (старый формат), используется симметричное приближение width/2 — это помечается.
    """
    early, late = [], []
    exact = True
    for r in results:
        recs = sorted(r["records"].get(model, []), key=lambda x: x["origin"])
        half = len(recs) // 2
        early += recs[:half]
        late += recs[half:]
    if not early or not late:
        return {"k": 1.0, "note": "мало отсечек для калибровки"}

    def cover(recs: list[dict[str, Any]], k: float) -> float:
        nonlocal exact
        hits = tot = 0
        for x in recs:
            e = np.array(x["err"])  # p50 − факт
            if "lo_off" in x:
                lo, hi = np.array(x["lo_off"]), np.array(x["hi_off"])
            else:
                exact = False
                lo = hi = np.array(x["width"]) / 2
            hits += int(((e <= k * lo) & (-e <= k * hi)).sum())
            tot += len(e)
        return hits / max(tot, 1)

    best = min(grid, key=lambda k: abs(cover(early, k) - target))
    return {"k": float(best), "target": target,
            "coverage_early_before": round(cover(early, 1.0), 4), "coverage_early_after": round(cover(early, best), 4),
            "coverage_late_before": round(cover(late, 1.0), 4), "coverage_late_after": round(cover(late, best), 4),
            "n_early": len(early), "n_late": len(late), "exact": exact}


def compare_models(df: Any, **kwargs: Any) -> pd.DataFrame:
    """Таблица метрик (строки — подходы) для слайда."""
    res = df if isinstance(df, dict) and "records" in df else backtest(df, **kwargs)
    met = res["metrics"] if "metrics" in res else res
    return metrics_table(met)


def metrics_table(met: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for m, v in met.items():
        if m.startswith("_"):
            continue
        g = v["gaps_without_owner_rescue"]
        rows.append({
            "model": m,
            "MAE остатка, % мес. оборота": v["balance_mae_pct_turnover"],
            "MAE на 7/14/30 день, %": "/".join(f"{x:.0%}" for x in v["balance_mae_pct_turnover_h7_h14_h30"]),
            "WAPE остатка": v["balance_wape"],
            "WAPE потоков (нед.) in/out": f"{v['inflow_wape_weekly']:.2f}/{v['outflow_wape_weekly']:.2f}",
            "Покрытие P10–P90 (норма 0.80)": v["coverage_p10_p90"],
            "Разрывы precision": g["precision"],
            "Разрывы recall": g["recall"],
            "Предупреждение за, дн. (медиана)": g["lead_days_median"],
            "Brier": g["brier"],
            "Прогнозов": v["n_forecasts"],
        })
    return pd.DataFrame(rows).set_index("model")
