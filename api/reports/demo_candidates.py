"""Кандидаты для демо из реального датасета: компании, у которых прогноз от последней операции показывает
вероятный кассовый разрыв через 7–21 день → api/reports/demo_candidates.md.

    CORE_PATH=core python -m api.reports.demo_candidates --workers 4
"""
from __future__ import annotations

import os

# один поток BLAS/OpenMP на процесс: иначе воркеры душат друг друга
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import argparse
import csv
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent


def _one(args: tuple[str, str, int]) -> dict[str, Any] | None:
    path, cid, n_sims = args
    sys.path.insert(0, os.getenv("CORE_PATH", str(ROOT / "core")))
    import cashflow_core as cc

    try:
        r = cc.forecast(path, [], 30, company_id=cid, n_sims=n_sims)
    except Exception:  # noqa: BLE001
        return None
    if not r.get("as_of"):
        return None
    as_of = date.fromisoformat(r["as_of"])
    best = None
    for k in r.get("risks", []):
        days = (date.fromisoformat(k["date"]) - as_of).days
        if 7 <= days <= 21 and (best is None or k["probability"] > best["probability"]):
            best = dict(k, days=days)
    if best is None:
        return None
    return {"company_id": cid, "as_of": r["as_of"], "balance": r.get("current_balance"), "date": best["date"],
            "days": best["days"], "probability": best["probability"], "severity": best["severity"],
            "shortfall": best["shortfall_amount"], "reason": best["reason"]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--n-sims", type=int, default=1000)
    args = ap.parse_args()
    raw = ROOT / "data" / "raw"
    comps = {r["company_id"]: r for r in csv.DictReader((raw / "companies.csv").open(encoding="utf-8-sig"), delimiter=";")}
    tasks = [(str(raw / "statements" / f"{cid}.csv"), cid, args.n_sims) for cid in comps]
    found = []
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for res in ex.map(_one, tasks):
            if res:
                found.append(res)
                print(res["company_id"], res["date"], res["probability"], flush=True)
    found.sort(key=lambda x: (-(x["severity"] == "high"), -x["probability"], abs(x["days"] - 14)))
    lines = ["# Кандидаты для демо из датасета организаторов", "",
             "Прогноз ядра по полной выписке (без дополнительных источников): риск разрыва через 7–21 день после "
             "последней операции. Сортировка — высокий риск, вероятность, близость к «через 2 недели».", "",
             "| компания | отрасль | последняя операция | остаток | разрыв | через, дн. | вероятность | нехватка (P90) | причина |",
             "|---|---|---|---:|---|---:|---:|---:|---|"]
    for f in found[:25]:
        c = comps[f["company_id"]]
        rub = (lambda x: f"{x:,.0f}".replace(",", " "))
        lines.append(f"| {f['company_id']} {c['company_name']} | {c['industry']} | {f['as_of']} | {rub(f['balance'] or 0)} | {f['date']} | "
                     f"{f['days']} | {f['probability']:.0%} | {rub(f['shortfall'])} | {f['reason'][:160]} |")
    lines += ["", f"Всего компаний с таким риском: {len(found)} из {len(comps)}.", ""]
    (OUT / "demo_candidates.md").write_text("\n".join(lines), encoding="utf-8")
    print("→", OUT / "demo_candidates.md")


if __name__ == "__main__":
    main()
