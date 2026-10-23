"""Машинно-читаемый прогноз для контрольного датасета.

    python -m cashflow_core.predict <CSV | папка> --horizon 30 --out predictions.csv

Для каждой компании берётся последняя дата в её выписке (данных «из будущего» нет:
модель видит только строки выписки), строится прогноз остатка по дням на
``horizon`` дней вперёд и риски разрывов. Пишутся два файла:

* ``<out>.csv`` — ``company_id, date, balance_forecast, balance_low, balance_high``
  (медиана и границы P10/P90 по Monte Carlo), ровно ``horizon`` строк на компанию;
* ``<out>.json`` — по компаниям: дата последней операции, текущий остаток, подушка
  безопасности, риски (``date, shortfall_amount, probability, severity, kind, reason``),
  предупреждения и статус.

Детерминированно: фиксированный seed, порядок по ``company_id``, без временных меток —
одинаковый вход даёт побайтно одинаковый выход при любом числе процессов. Компания,
для которой прогноз построить не удалось, всё равно попадает в файл (остаток не меняется,
``status: "fallback"`` и причина в ``warnings``).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .evaluate import discover
from .parallel import make_pool

CSV_COLUMNS = ["company_id", "date", "balance_forecast", "balance_low", "balance_high"]


def predict_company(cid: str, src: Any, horizon: int = 30, seed: int = 42, n_sims: int = 2000) -> dict[str, Any]:
    """Прогноз одной компании в виде {company_id, rows, risks, ...}. Никогда не бросает исключение."""
    from .engine import build_plan, build_state, ensure_error_horizon, simulate
    from .io import load_statement
    from .risk import find_risks
    from .schema import INTERVAL_HIGH_Q, INTERVAL_LOW_Q

    out: dict[str, Any] = {"company_id": cid, "status": "ok", "warnings": [], "risks": []}
    try:
        st = build_state(src, [], horizon, company_id=cid if not isinstance(src, (str, Path)) else None,
                         n_sims=n_sims, seed=seed)
        ensure_error_horizon(st, horizon)
        plan = build_plan(st, horizon)
        sim = simulate(st, plan)
        q = np.quantile(sim.balances, [INTERVAL_LOW_Q, 0.5, INTERVAL_HIGH_Q], axis=0)
        out["rows"] = [[cid, d.isoformat(), round(float(q[1, k]), 2), round(float(q[0, k]), 2), round(float(q[2, k]), 2)]
                       for k, d in enumerate(plan.dates)]
        out["risks"] = find_risks(st, plan, sim, with_kind=True)
        out.update(as_of=st.as_of.isoformat(), current_balance=round(float(st.start_balance), 2),
                   comfort_balance=round(float(st.settings.get("comfort_balance") or 0.0), 2),
                   warnings=list(dict.fromkeys(st.warnings + plan.warnings)), mode=st.mode)
        if not len(st.df):
            out["status"] = "fallback"
        return out
    except Exception as exc:  # noqa: BLE001 — одна плохая выписка не должна ломать весь файл
        out["status"] = "fallback"
        out["warnings"] = [f"Прогноз не построен ({type(exc).__name__}): остаток показан без изменений."]
    # запасной вариант: последний известный остаток без изменений
    try:
        tx = load_statement(src, company_id=cid if not isinstance(src, (str, Path)) else None)
        bal = float(tx["balance_eod"].dropna().iloc[-1]) if tx["balance_eod"].notna().any() else 0.0
        last = pd.to_datetime(tx["date"]).max().date() if len(tx) else date.today()
    except Exception:  # noqa: BLE001
        bal, last = 0.0, date.today()
    out.update(as_of=last.isoformat(), current_balance=round(bal, 2), comfort_balance=0.0)
    out["rows"] = [[cid, (last + timedelta(days=k + 1)).isoformat(), round(bal, 2), round(bal, 2), round(bal, 2)]
                   for k in range(horizon)]
    return out


def _job(args: tuple[str, Any, int, int, int]) -> dict[str, Any]:
    return predict_company(*args)


def _paths(out: str | Path) -> tuple[Path, Path]:
    p = Path(out)
    stem = p.with_suffix("") if p.suffix.lower() in (".csv", ".json") else p
    return stem.with_suffix(".csv"), stem.with_suffix(".json")


def predict(path: str | Path, out: str | Path, horizon: int = 30, seed: int = 42, n_sims: int = 2000,
            workers: int = 1) -> tuple[Path, Path, list[dict[str, Any]]]:
    """Построить прогноз для всех компаний из ``path`` и записать CSV + JSON."""
    comps = discover(path)
    jobs = [(cid, src, int(horizon), int(seed), int(n_sims)) for cid, src in comps]
    if workers > 1 and len(jobs) > 1:
        with make_pool(workers) as ex:
            results = list(ex.map(_job, jobs))
    else:
        results = [_job(j) for j in jobs]
    results.sort(key=lambda r: r["company_id"])
    csv_path, json_path = _paths(out)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_COLUMNS)
        for r in results:
            w.writerows(r["rows"])
    payload = {
        "horizon_days": int(horizon), "seed": int(seed), "n_sims": int(n_sims),
        "interval": {"balance_forecast": "медиана (P50)", "balance_low": "P10", "balance_high": "P90"},
        "companies": [{k: r.get(k) for k in ("company_id", "status", "as_of", "current_balance", "comfort_balance",
                                              "risks", "warnings")} for r in results],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return csv_path, json_path, results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Прогноз остатка по дням для каждой компании (CSV + JSON)")
    ap.add_argument("path", help="CSV в формате датасета (одна или много компаний) или папка с выписками")
    ap.add_argument("--horizon", type=int, default=30)
    ap.add_argument("--out", default="predictions.csv", help="путь к CSV; JSON с рисками ляжет рядом (.json)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--sims", type=int, default=2000)
    ap.add_argument("--workers", type=int, default=max(1, min(4, os.cpu_count() or 1)))
    a = ap.parse_args(argv)
    if not Path(a.path).exists():
        print(f"Не найдено: {a.path}")
        return 2
    import time

    t = time.time()
    csv_path, json_path, results = predict(a.path, a.out, a.horizon, a.seed, a.sims, a.workers)
    fb = [r["company_id"] for r in results if r["status"] != "ok"]
    print(f"Компаний: {len(results)}, строк: {sum(len(r['rows']) for r in results)}, "
          f"с рисками: {sum(1 for r in results if r['risks'])}, запасной вариант: {fb or 'нет'}; {time.time() - t:.1f} с")
    print(f"CSV:  {csv_path}\nJSON: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
