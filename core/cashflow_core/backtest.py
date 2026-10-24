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

DEFAULT_MODELS = ("flat", "naive", "ets", "hybrid")


@dataclass
class OriginForecast:
    balances: np.ndarray
    exp_in: np.ndarray
    exp_out: np.ndarray
    state: Any = None


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


def _flat(daily_hist: pd.DataFrame, H: int, n_sims: int, seed: int, b0: float) -> OriginForecast:
    bal = daily_hist["balance_reported"].where(daily_hist["balance_reported"].notna(), daily_hist["balance"])
    b = bal.ffill().to_numpy(dtype=float)
    n = len(b) - H
    zeros = np.zeros(H)
    if n < 5:
        return OriginForecast(np.full((n_sims, H), b0), zeros, zeros)
    paths = np.array([b[s + 1:s + H + 1] - b[s] for s in range(n)])
    paths = paths - np.median(paths, axis=0)
    pick = np.random.default_rng([seed, 1]).integers(0, n, n_sims)
    return OriginForecast(b0 + paths[pick], zeros, zeros)


def _hybrid(tx: pd.DataFrame, origin: date, H: int, n_sims: int, seed: int, model: str,
            interval_scale: float = 1.0) -> OriginForecast:
    st = build_state(tx, [], H, as_of=origin, n_sims=n_sims, seed=seed, model=model, interval_scale=interval_scale)
    plan = build_plan(st, H)
    sim = simulate(st, plan)
    return OriginForecast(sim.balances, sim.det_in + plan.res_in, sim.det_out + plan.res_out, st)


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


def _recurring_hits(tx: pd.DataFrame, origin: date, H: int, state: Any) -> dict[str, Any]:
    from .recurring import _cp_key

    if state is None or not state.patterns or state.categorizer is None:
        return {"n": 0}
    d = pd.to_datetime(tx["date"]).dt.date
    fut = tx[(d > origin) & (d <= origin + timedelta(days=H + 3))]
    if not len(fut):
        return {"n": 0}
    fut_c = state.categorizer.transform(fut)
    fut_c["d"] = pd.to_datetime(fut_c["date"]).dt.date
    fut_c["cp"] = [_cp_key(i, n) for i, n in zip(fut_c["counterparty_inn"], fut_c["counterparty_name"])]
    n = hits = 0
    amt_err = []
    for p in state.patterns:
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
             company_id: str | None = None, hybrid_model: str = "auto", recurring_check: bool = True,
             interval_scale: float = 1.0) -> dict[str, Any]:
    tx = df if isinstance(df, pd.DataFrame) and "tx_id" in df.columns else load_statement(df, company_id=company_id)
    cid = str(company_id or tx.attrs.get("company_id") or "unknown")
    tx = tx.copy()
    tx.attrs = {}
    from .categorize import rule_category

    tx_cat = tx.copy()
    tx_cat["category"] = [rule_category(p, n, d)[0] or "other"
                          for p, n, d in zip(tx["purpose"], tx["counterparty_name"], tx["direction"])]
    daily = to_daily(tx)
    resc = tx_cat[(tx_cat["direction"] == "in") & tx_cat["category"].isin(RESCUE_INFLOW_CATEGORIES)]
    rescue_daily = resc.groupby(pd.to_datetime(resc["date"]))["amount"].sum()
    H = int(horizon)
    origins = _origins(daily, H, n_origins, step, min_train)
    if not origins and len(daily) >= 45 + H:
        origins = _origins(daily, H, min(3, n_origins), 14, 45)
    records: dict[str, list[dict[str, Any]]] = {m: [] for m in models}
    rec_stats = {"n": 0, "hits": 0, "amount_ape": []}
    for o in origins:
        act = _actual(daily, tx_cat, o, H)
        turnover = float(daily.loc[:pd.Timestamp(o)].iloc[-30:]["outflow"].sum()) or 1.0
        hybrid_state = None
        for m in models:
            t0 = time.time()
            try:
                if m == "flat":
                    fc = _flat(daily.loc[:pd.Timestamp(o)], H, n_sims, seed, act["b0"])
                elif m == "hybrid":
                    fc = _hybrid(tx, o, H, n_sims, seed, hybrid_model, interval_scale)
                elif m.startswith("hybrid_"):
                    fc = _hybrid(tx, o, H, n_sims, seed, m.split("_", 1)[1], interval_scale)
                else:
                    fc = _baseline(daily.loc[:pd.Timestamp(o)], m, H, n_sims, seed, act["b0"], rescue_daily)
            except Exception as exc:
                log.warning("backtest model failed: %s %s", m, type(exc).__name__)
                continue
            if fc.state is not None and hybrid_state is None:
                hybrid_state = fc.state
            q = np.quantile(fc.balances, [INTERVAL_LOW_Q, 0.5, INTERVAL_HIGH_Q], axis=0)
            p_gap = (fc.balances < threshold).mean(axis=0)
            target = act["need"]
            records[m].append({
                "origin": o.isoformat(), "b0": act["b0"], "turnover30": turnover,
                "err": (q[1] - target).tolist(),
                "err_vs_actual": (q[1] - act["balance"]).tolist(),
                "p50": q[1].tolist(), "bal_act": act["balance"].tolist(),
                "mode": getattr(fc.state, "mode", None), "hist_days": int(len(daily.loc[:pd.Timestamp(o)])),
                "covered_actual": ((act["balance"] >= q[0]) & (act["balance"] <= q[2])).tolist(),
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
                r = _recurring_hits(tx, o, H, hybrid_state)
                if r.get("n"):
                    rec_stats["n"] += r["n"]
                    rec_stats["hits"] += r["hits"]
                    rec_stats["amount_ape"] += r["amount_ape"]
            except Exception as exc:
                log.warning("recurring check failed: %s", type(exc).__name__)
    out = {"company_id": cid, "origins": [o.isoformat() for o in origins], "records": records, "recurring": rec_stats}
    out["metrics"] = aggregate([out])
    return out


def _gap_metrics(recs: list[dict[str, Any]], key: str) -> dict[str, Any]:
    tp = fp = fn = tn = 0
    leads, date_err, brier = [], [], []
    for r in recs:
        if r["b0"] < 0:
            continue
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

        has_act = all("bal_act" in x for x in recs)
        ea = np.array([x["err_vs_actual"] for x in recs])
        aa = np.abs(np.array([x["bal_act"] for x in recs])) if has_act else None
        out[m] = {
            "n_forecasts": len(recs),
            "actual_balance_mae_rub": round(float(np.abs(ea).mean()), 0),
            "actual_balance_wape": round(float(np.abs(ea).sum() / max(aa.sum(), 1.0)), 4) if has_act else None,
            "actual_balance_mae_pct_turnover": round(float(np.median((np.abs(ea) / turn).mean(axis=1))), 4),
            "actual_balance_mae_pct_turnover_h7_h14_h30": [round(float(np.median(np.abs(ea[:, h]) / turn[:, 0])), 4)
                                                           for h in (6, 13, H - 1)],
            "actual_coverage_p10_p90": round(float(np.mean([x["covered_actual"] for x in recs])), 4) if has_act else None,
            "actual_balance_mae_pct_turnover_by_h": [round(float(np.median(np.abs(ea[:, h]) / turn[:, 0])), 4)
                                                     for h in range(H)],
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
            e = np.array(x["err"])
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


def _coverage_with_scale(results: list[dict[str, Any]], k: float, model: str = "hybrid") -> float:
    hits = tot = 0
    for r in results:
        for x in r["records"].get(model, []):
            e = np.array(x["err"])
            lo = np.array(x.get("lo_off", np.array(x["width"]) / 2))
            hi = np.array(x.get("hi_off", np.array(x["width"]) / 2))
            hits += int(((e <= k * lo) & (-e <= k * hi)).sum())
            tot += len(e)
    return round(hits / max(tot, 1), 4)


def calibrate_on(results: list[dict[str, Any]], model: str = "hybrid", target: float = 0.8) -> float:
    grid = np.round(np.arange(0.8, 3.01, 0.05), 2)
    return float(min(grid, key=lambda k: abs(_coverage_with_scale(results, k, model) - target)))


def compare_models(df: Any, **kwargs: Any) -> pd.DataFrame:
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
            "Факт: WAPE остатка": v.get("actual_balance_wape"),
            "Факт: MAE, ₽": v.get("actual_balance_mae_rub"),
            "Факт: MAE, % мес. оборота": v.get("actual_balance_mae_pct_turnover"),
            "Факт: покрытие P10–P90": v.get("actual_coverage_p10_p90"),
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
