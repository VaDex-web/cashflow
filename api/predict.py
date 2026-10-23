"""Прогноз для проверки на контрольном датасете — без регистрации и без интерфейса.

Для каждой компании берётся последняя дата её выписки, прогноз остатка строится на ``horizon`` дней вперёд
только по операциям до этой даты (без событий из источников, порог разрыва 0 ₽, фиксированный seed).
Тот же результат, что ``python -m cashflow_core.predict``: ядро вызывается через его публичную функцию ``forecast``.

    python -m api.predict data/raw/statements --horizon 30 --out predictions.csv --workers 4
    python -m api.predict data/raw/all_operations.csv --out out/pred.csv
    python -m api.predict file.csv --api http://localhost:8000          # то же через POST /api/predict

Пишет два файла:
* ``<out>.csv`` — ``company_id;date;balance_forecast;balance_low;balance_high`` (UTF-8, разделитель «;» — как датасет);
* ``<out>_risks.json`` — по компаниям: последняя дата, остаток, риски разрывов (дата, сумма нехватки, вероятность),
  предупреждения.

Формат входа — как в ``data/raw/README.md`` (колонки датасета организаторов); файл или папка с CSV.
"""
from __future__ import annotations

import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import argparse  # noqa: E402
import csv  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from concurrent.futures import ProcessPoolExecutor  # noqa: E402
from datetime import date, datetime, timedelta, timezone  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SEED = 42
COLUMNS = ["company_id", "operation_id", "operation_date", "amount", "direction", "counterparty_inn", "counterparty_name",
           "payment_purpose", "balance_eod"]
CSV_FIELDS = ["company_id", "date", "balance_forecast", "balance_low", "balance_high"]


class PredictError(ValueError):
    """Ошибка входного файла — текст для человека."""


# --------------------------------------------------------------------------- вход
def read_csv_bytes(raw: bytes, name: str = "файл") -> pd.DataFrame:
    """Выписка в формате датасета (UTF-8 с BOM или без, «;»). ИНН — строкой."""
    if not raw.strip():
        raise PredictError(f"{name}: файл пустой")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1251")
    df = pd.read_csv(io.StringIO(text), sep=";", dtype=str, keep_default_na=False)
    df.columns = [c.strip().lstrip("﻿") for c in df.columns]
    missing = [c for c in ("operation_date", "amount", "direction", "balance_eod") if c not in df.columns]
    if missing:
        raise PredictError(f"{name}: нет колонок {', '.join(missing)} (нужен формат датасета: {';'.join(COLUMNS)})")
    if "company_id" not in df.columns or not (df["company_id"].str.strip() != "").any():
        df["company_id"] = Path(name).stem or "company"
    return df


def read_inputs(path: str | Path) -> dict[str, pd.DataFrame]:
    """Файл или папка → {company_id: операции}. В папке: файлы с операциями (справочник companies.csv пропускается);
    если компания встречается и в отдельной выписке, и в all_operations.csv — берётся отдельная выписка."""
    p = Path(path)
    if not p.exists():
        raise PredictError(f"Не найден путь {p}")
    files = sorted(p.rglob("*.csv")) if p.is_dir() else [p]
    files.sort(key=lambda f: (f.name == "all_operations.csv", str(f)))
    out: dict[str, pd.DataFrame] = {}
    for f in files:
        try:
            df = read_csv_bytes(f.read_bytes(), f.name)
        except PredictError:
            if p.is_dir():
                continue          # справочники и посторонние CSV в папке пропускаем
            raise
        for cid, part in df.groupby(df["company_id"].str.strip(), sort=True):
            out.setdefault(str(cid), part.reset_index(drop=True))
    if not out:
        raise PredictError(f"В {p} не найдено ни одной выписки в формате датасета")
    return out


# --------------------------------------------------------------------------- прогноз
def _core():
    sys.path.insert(0, os.getenv("CORE_PATH", str(ROOT / "core")))
    import cashflow_core  # noqa: PLC0415

    return cashflow_core


def predict_company(cid: str, df: pd.DataFrame, horizon: int = 30, n_sims: int = 2000, seed: int = SEED
                    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Прогноз одной компании от её последней даты. Не бросает исключений: проблемы — в warnings."""
    t0 = time.time()
    warnings: list[str] = []
    res: dict[str, Any] = {}
    try:
        res = _core().forecast(df, [], horizon, company_id=cid, n_sims=n_sims, seed=seed, threshold=0.0)
        warnings = list(res.get("warnings") or [])
    except Exception as exc:  # noqa: BLE001 — на контрольном датасете не падаем
        warnings.append(f"Прогноз ядра не построен ({type(exc).__name__}) — показан неизменный остаток.")
    daily = res.get("daily") or []
    as_of = res.get("as_of")
    balance = res.get("current_balance")
    if not daily:
        # запасной вариант: остаток последнего дня без изменений
        d = pd.to_datetime(df["operation_date"], errors="coerce")
        last = d.max()
        bal = pd.to_numeric(df["balance_eod"].str.replace(",", ".", regex=False), errors="coerce")
        balance = float(bal[d == last].dropna().iloc[-1]) if pd.notna(last) and bal[d == last].notna().any() else 0.0
        start = last.date() if pd.notna(last) else date.today()
        as_of = start.isoformat()
        daily = [{"date": (start + timedelta(days=k)).isoformat(), "balance_p50": balance, "balance_low": balance,
                  "balance_high": balance} for k in range(1, horizon + 1)]
        if not any("неизменный остаток" in w for w in warnings):
            warnings.append("Прогноз не построен — показан неизменный остаток последнего дня.")
    rows = [{"company_id": cid, "date": p["date"], "balance_forecast": round(float(p["balance_p50"]), 2),
             "balance_low": round(float(p["balance_low"]), 2), "balance_high": round(float(p["balance_high"]), 2)}
            for p in daily[:horizon]]
    info = {"company_id": cid, "as_of": as_of, "current_balance": balance, "horizon_days": len(rows),
            "risks": [{"date": r["date"], "shortfall_amount": round(float(r["shortfall_amount"]), 2),
                       "probability": round(float(r["probability"]), 4), "severity": r.get("severity")}
                      for r in res.get("risks", [])],
            "warnings": warnings, "secs": round(time.time() - t0, 2)}
    return rows, info


def _task(args: tuple[str, pd.DataFrame, int, int, int]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return predict_company(*args)


def run(companies: dict[str, pd.DataFrame], horizon: int = 30, workers: int = 1, n_sims: int = 2000,
        seed: int = SEED) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    t0 = time.time()
    tasks = [(cid, df, horizon, n_sims, seed) for cid, df in companies.items()]
    if workers > 1 and len(tasks) > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(_task, tasks))
    else:
        results = [_task(t) for t in tasks]
    rows = [r for rs, _ in results for r in rs]
    meta = {"generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(), "horizon_days": horizon,
            "seed": seed, "n_sims": n_sims, "threshold": 0.0, "companies_count": len(results),
            "secs_total": round(time.time() - t0, 1), "companies": [info for _, info in results]}
    return rows, meta


# --------------------------------------------------------------------------- выход
def to_csv(rows: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_FIELDS, delimiter=";", lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: (f"{r[k]:.2f}" if isinstance(r[k], float) else r[k]) for k in CSV_FIELDS})
    return buf.getvalue()


def write(rows: list[dict[str, Any]], meta: dict[str, Any], out: str | Path) -> tuple[Path, Path]:
    out = Path(out)
    csv_path = out if out.suffix.lower() == ".csv" else out.with_suffix(".csv")
    json_path = csv_path.with_name(csv_path.stem + "_risks.json")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text(to_csv(rows), encoding="utf-8")
    json_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return csv_path, json_path


def _via_api(path: Path, url: str, horizon: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    import httpx  # noqa: PLC0415

    files = [path] if path.is_file() else sorted(path.glob("*.csv"))
    rows, comps = [], []
    for f in files:
        r = httpx.post(f"{url.rstrip('/')}/api/predict", params={"horizon": horizon},
                       files={"file": (f.name, f.read_bytes(), "text/csv")}, timeout=3600)
        if r.status_code != 200:
            print(f"{f.name}: {r.status_code} {r.text[:200]}", file=sys.stderr)
            continue
        j = r.json()
        rows += j["forecast"]
        comps += j["companies"]
    return rows, {"horizon_days": horizon, "seed": SEED, "companies": comps, "companies_count": len(comps)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Прогноз остатка по дням для каждой компании (контрольный датасет)")
    ap.add_argument("path", help="CSV в формате датасета или папка с CSV")
    ap.add_argument("--horizon", type=int, default=30)
    ap.add_argument("--out", default="predictions.csv", help="CSV с прогнозом; риски — в <out>_risks.json")
    ap.add_argument("--workers", type=int, default=1, help="параллельных процессов (по компаниям)")
    ap.add_argument("--n-sims", type=int, default=2000)
    ap.add_argument("--api", default=None, help="адрес сервера (http://localhost:8000) — считать через POST /api/predict")
    a = ap.parse_args()
    try:
        if a.api:
            rows, meta = _via_api(Path(a.path), a.api, a.horizon)
        else:
            rows, meta = run(read_inputs(a.path), a.horizon, a.workers, a.n_sims)
    except PredictError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        sys.exit(2)
    c, j = write(rows, meta, a.out)
    risky = sum(1 for x in meta["companies"] if any(r["probability"] >= 0.5 for r in x["risks"]))
    print(f"Компаний: {meta['companies_count']}, строк прогноза: {len(rows)}, с вероятным разрывом: {risky}; "
          f"время: {meta.get('secs_total', '—')} с\n→ {c}\n→ {j}")


if __name__ == "__main__":
    main()
