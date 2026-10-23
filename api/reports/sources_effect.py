"""Отчёт «как источник улучшил прогноз» → api/reports/sources_effect.md (+ sources_effect.json).

Часть А — синтетика с известным будущим (data/synthetic/future): тот же путь, что в API
(синхронизация источника → прогноз), прогон «без источника» и «с источником», сравнение с фактом.
Часть Б — бэктест на реальных выписках организаторов: прогноз строится на дату за 30 дней до конца
выписки, факт — последние 30 дней. Честно считаются только источники, которые не знают будущего
(налоговый календарь, банк по истории); «1С» на реальных данных — имитация (известна часть будущих
поступлений по счетам с ошибкой даты ±3 раб. дня), помечена отдельно.

Запуск из корня репозитория:
    CORE_PATH=core python -m api.reports.sources_effect            # обе части (~10 мин на 4 ядрах)
    python -m api.reports.sources_effect --part A                     # только синтетика
    python -m api.reports.sources_effect --companies 40 --workers 4
"""
from __future__ import annotations

import os

# один поток BLAS/OpenMP на процесс: иначе воркеры душат друг друга
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import argparse
import json
import random
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HORIZON = 30
SOURCES_A = ["tax_calendar", "bank", "1c", "registry", "contracts"]
TITLES = {"base": "только выписка", "tax_calendar": "+ налоговый календарь", "bank": "+ банк", "1c": "+ 1С",
          "registry": "+ открытые реестры", "contracts": "+ договоры", "1c+registry": "+ 1С + реестры",
          "all": "все источники", "tax+bank": "+ налоги + банк", "1c_sim": "+ 1С (имитация)", "all_sim": "все (с имитацией 1С)"}


# --------------------------------------------------------------------------- метрики
def truth_series(as_of: date, fut: pd.DataFrame, start_balance: float) -> pd.Series:
    """Фактический остаток на конец каждого календарного дня горизонта."""
    days = [as_of + timedelta(days=k) for k in range(1, HORIZON + 1)]
    f = fut.copy()
    f["d"] = pd.to_datetime(f["date"]).dt.date
    eod = f.groupby("d")["balance_eod"].last()
    out, bal = [], start_balance
    for d in days:
        if d in eod.index:
            bal = float(eod[d])
        out.append(bal)
    return pd.Series(out, index=days)


def metrics(res: dict[str, Any], truth: pd.Series) -> dict[str, Any]:
    daily = {date.fromisoformat(p["date"]): p for p in res.get("daily", [])}
    rows = [(daily[d]["balance_p50"], daily[d]["balance_low"], daily[d]["balance_high"], v) for d, v in truth.items() if d in daily]
    if not rows:
        return {}
    p50, lo, hi, t = map(np.array, zip(*rows))
    scale = max(float(np.mean(np.abs(t))), 1.0)
    true_gap_days = [d for d, v in truth.items() if v < 0]
    first_true = min(true_gap_days) if true_gap_days else None
    risks = res.get("risks", [])
    likely = [r for r in risks if r["probability"] >= 0.5]
    near = [r for r in risks if first_true and abs((date.fromisoformat(r["date"]) - first_true).days) <= 5]
    return {
        "mae": float(np.mean(np.abs(p50 - t))), "mape": float(np.mean(np.abs(p50 - t)) / scale),
        "coverage_80": float(np.mean((t >= lo) & (t <= hi))),
        "true_gap": first_true.isoformat() if first_true else None,
        "true_min": float(t.min()),
        "pred_gap": min((r["date"] for r in likely), default=None),
        "prob_at_true_gap": max((r["probability"] for r in near), default=0.0),
        "max_prob": max((r["probability"] for r in risks), default=0.0),
        "detected": bool(first_true and any(abs((date.fromisoformat(r["date"]) - first_true).days) <= 5 for r in likely)),
        "false_alarm": bool(not first_true and likely),
    }


# --------------------------------------------------------------------------- часть А: синтетика через API
def part_a() -> list[dict[str, Any]]:
    from fastapi.testclient import TestClient

    from api import core_adapter, db, services
    from api.config import reset_settings
    from api.main import create_app

    syn = ROOT / "data" / "synthetic"
    tmp = Path(tempfile.mkdtemp(prefix="sources_effect_"))
    reset_settings(use_stub_core=False, data_dir=tmp, database_url=f"sqlite:///{tmp / 'r.db'}",
                   jwt_secret="report-secret-0123456789abcdef0123456789", users="report:report")
    core_adapter.reset_core()
    services.reset_cache()
    db.init_db()
    results = []
    with TestClient(create_app()) as c:
        tok = c.post("/api/auth/login", json={"username": "report", "password": "report"}).json()["access_token"]
        h = {"Authorization": f"Bearer {tok}"}
        for cid in ["S01", "S02", "S03", "S04", "S05"]:
            raw = (syn / "statements" / f"{cid}.csv").read_bytes()
            fut = pd.read_csv(syn / "future" / f"{cid}.csv", sep=";", encoding="utf-8-sig", dtype={"counterparty_inn": str})
            fut = fut.rename(columns={"operation_date": "date"})
            hist = pd.read_csv(syn / "statements" / f"{cid}.csv", sep=";", encoding="utf-8-sig", dtype={"counterparty_inn": str})
            as_of = date.fromisoformat(hist["operation_date"].max())
            truth = truth_series(as_of, fut, float(hist["balance_eod"].iloc[-1]))
            configs = [("base", [])] + [(s, [s]) for s in SOURCES_A] + [("1c+registry", ["1c", "registry"]), ("all", SOURCES_A)]
            for name, srcs in configs:
                t0 = time.time()
                up = c.post("/api/companies", headers=h, files={"file": (f"{cid}.csv", raw, "text/csv")}).json()
                comp = up["company_id"]
                # разрыв для метрик — «денег меньше нуля», поэтому комфортный минимум владельца здесь 0
                c.put(f"/api/companies/{comp}/settings", headers=h, json={"safety_cushion": 0})
                for s in srcs:
                    c.post(f"/api/companies/{comp}/integrations/{s}/sync", headers=h)
                f = c.get(f"/api/companies/{comp}/forecast?horizon={HORIZON}", headers=h).json()
                m = metrics(f, truth)
                evs = c.get(f"/api/companies/{comp}/events", headers=h).json()
                m.update({"company": cid, "config": name, "secs": round(time.time() - t0, 1), "events": len(evs)})
                if name == "tax_calendar":
                    fact = fut[fut["counterparty_name"].astype(str).str.contains("ФНС")]
                    m["tax_check"] = [{"date": e["date"], "estimate": e["amount"],
                                       "actual": float(fact.loc[fact["date"] == e["date"], "amount"].sum())}
                                      for e in evs if e["type"] == "tax" and e["date"] <= str(fut["date"].max())]
                results.append(m)
                print(f"A {cid} {name:12s} MAE {m['mae']:>11,.0f}  cover {m['coverage_80']:.0%}  "
                      f"p(gap) {m['prob_at_true_gap']:.2f}  detected={m['detected']}  false={m['false_alarm']}", flush=True)
    return results


# --------------------------------------------------------------------------- часть Б: реальные выписки
def _simulated_1c(fut: pd.DataFrame, seed: int) -> list[dict[str, Any]]:
    """Имитация 1С: учёт знает ~80% будущих поступлений по счетам/договорам; дата оплаты — с ошибкой ±3 раб. дня."""
    from api.integrations.base import next_business_day

    rnd = random.Random(seed)
    out = []
    f = fut[(fut["direction"] == "in") & fut["counterparty_inn"].astype(str).str.len().isin([10, 12])]
    f = f[f["purpose"].astype(str).str.contains(r"(?i)сч[её]т|упд|договор|акт", regex=True) & (f["amount"] >= 30_000)]
    for i, r in enumerate(f.itertuples(index=False)):
        if rnd.random() > 0.8:
            continue
        d = pd.Timestamp(r.date).date() + timedelta(days=rnd.randint(-4, 4))
        out.append({"id": f"sim1c-{i}", "type": "invoice", "direction": "in", "amount": float(r.amount),
                    "date": next_business_day(d).isoformat(), "source": "1c", "status": "expected",
                    "counterparty": str(r.counterparty_name), "note": "имитация выгрузки 1С"})
    return out


def _one_company(args: tuple[str, str, int]) -> list[dict[str, Any]]:
    path, cid, n_sims = args
    core_path = os.getenv("CORE_PATH", str(ROOT / "core"))
    if core_path not in sys.path:
        sys.path.insert(0, core_path)
    import cashflow_core as cc

    from api.core_adapter import RealCore
    from api.integrations import Bank, CompanyContext, TaxCalendar

    raw = cc.load_statement(path)
    raw.attrs = {}
    d = pd.to_datetime(raw["date"]).dt.date
    last = max(d)
    cut = last - timedelta(days=HORIZON)
    hist, fut = raw[d <= cut].reset_index(drop=True), raw[d > cut].reset_index(drop=True)
    if len(hist) < 100 or not len(fut):
        return []
    as_of = max(pd.to_datetime(hist["date"]).dt.date)
    bal_hist = hist["balance_eod"].dropna()
    truth = truth_series(as_of, fut, float(bal_hist.iloc[-1]) if len(bal_hist) else 0.0)
    plain = hist[["date", "amount", "direction", "counterparty_name", "counterparty_inn", "purpose", "balance_eod"]].copy()
    ctx = CompanyContext(company_id=cid, df=plain, as_of=as_of, core=RealCore(cc))
    tax = [e.model_dump(mode="json") for e in TaxCalendar().fetch(ctx)]
    bank = [e.model_dump(mode="json") for e in Bank().fetch(ctx)]
    sim = _simulated_1c(fut, seed=int(cid[1:]) if cid[1:].isdigit() else 1)
    configs = {"base": [], "tax_calendar": tax, "bank": bank, "tax+bank": tax + bank, "1c_sim": sim, "all_sim": tax + bank + sim}
    out = []
    base_state = None
    for name, events in configs.items():
        t0 = time.time()
        kw: dict[str, Any] = {"company_id": cid, "n_sims": n_sims}
        if base_state is not None:
            kw["categorizer"] = base_state.categorizer
        st = cc.build_state(base_state.df if base_state is not None else hist, [{k: v for k, v in e.items() if k != "counterparty_inn"} for e in events],
                            HORIZON, **kw)
        base_state = base_state or st
        res = cc.forecast_from_state(st, HORIZON)
        m = metrics(res, truth)
        m.update({"company": cid, "config": name, "events": len(events), "secs": round(time.time() - t0, 1)})
        out.append(m)
    return out


def part_b(n: int, workers: int, n_sims: int) -> list[dict[str, Any]]:
    import csv

    from .split import split

    raw_dir = ROOT / "data" / "raw"
    holdout = set(split()["holdout"])          # только отложенные компании: параметры подбирались на dev
    rows = list(csv.DictReader((raw_dir / "companies.csv").open(encoding="utf-8-sig"), delimiter=";"))
    rows = [r for r in rows if r["company_id"] in holdout
            and (date.fromisoformat(r["last_operation_date"]) - date.fromisoformat(r["first_operation_date"])).days > 300]
    pick = rows[:n]
    tasks = [(str(raw_dir / "statements" / f"{r['company_id']}.csv"), r["company_id"], n_sims) for r in pick]
    out: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for i, res in enumerate(ex.map(_one_company, tasks), 1):
            out.extend(res)
            if res:
                b = next(x for x in res if x["config"] == "base")
                a = next(x for x in res if x["config"] == "tax+bank")
                print(f"B {i:3d}/{len(tasks)} {res[0]['company']}: MAE base {b['mae']:>11,.0f} → tax+bank {a['mae']:>11,.0f}", flush=True)
    return out


# --------------------------------------------------------------------------- отчёт
def _agg(results: list[dict[str, Any]], configs: list[str]) -> list[dict[str, Any]]:
    df = pd.DataFrame(results)
    base = df[df["config"] == "base"].set_index("company")
    out = []
    for cfg in configs:
        part = df[df["config"] == cfg].set_index("company")
        if not len(part):
            continue
        common = part.index.intersection(base.index)
        gaps = part[part["true_gap"].notna()]
        nogap = part[part["true_gap"].isna()]
        pred = part[part["pred_gap"].notna()]
        rel = (part.loc[common, "mae"] / base.loc[common, "mae"].clip(lower=1) - 1) if len(common) else pd.Series(dtype=float)
        changed = rel[rel.abs() > 0.005]
        better = float((changed < 0).mean()) if len(changed) else 0.0
        out.append({
            "config": cfg, "title": TITLES.get(cfg, cfg), "companies": int(len(part)),
            "mae_median": float(part["mae"].median()), "mape_median": float(part["mape"].median()),
            "mae_change_vs_base": float((part.loc[common, "mae"] / base.loc[common, "mae"].clip(lower=1) - 1).median()) if len(common) else 0.0,
            "share_better": better, "n_better": int((changed < 0).sum()), "n_worse": int((changed > 0).sum()),
            "n_same": int(len(rel) - len(changed)),
            "change_if_changed": float(changed.median()) if len(changed) else 0.0,
            "coverage_80": float(part["coverage_80"].mean()),
            "gap_cases": int(len(gaps)), "gap_recall": float(gaps["detected"].mean()) if len(gaps) else None,
            "gap_precision": float(pred["true_gap"].notna().mean()) if len(pred) else None,
            "false_alarms": int(nogap["false_alarm"].sum()) if len(nogap) else 0,
            "prob_at_gap_mean": float(gaps["prob_at_true_gap"].mean()) if len(gaps) else None,
        })
    return out


def summary(data: dict[str, Any]) -> dict[str, Any]:
    """Сводка для GET /api/metrics/sources (раздел «Как это работает»)."""
    a, b = data.get("part_a", []), data.get("part_b", [])
    return {
        "synthetic": _agg(a, ["base", "tax_calendar", "bank", "1c", "registry", "contracts", "1c+registry", "all"]) if a else [],
        "showcase": [r for r in a if r.get("company") == "S02"],
        "real_holdout": _agg(b, ["base", "tax_calendar", "bank", "tax+bank", "1c_sim", "all_sim"]) if b else [],
        "real_companies": sorted({r["company"] for r in b}),
    }


def _fmt_rub(x: float) -> str:
    return f"{x:,.0f}".replace(",", " ") + " ₽"


def _pct(x: float | None, signed: bool = False) -> str:
    if x is None:
        return "—"
    return f"{x:+.0%}" if signed else f"{x:.0%}"


def write_report(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> None:
    lines = ["# Как источники данных улучшают прогноз", "",
             "Отчёт генерируется скриптом `python -m api.reports.sources_effect` (данные — `sources_effect.json`).",
             "Каждый источник подключается через тот же код, что и в API (`Integration.fetch(company) → Event[]`), "
             "прогноз строит ядро `cashflow_core`. Метрики: **MAE** — средняя ошибка ожидаемого остатка (P50) за 30 дней, ₽; "
             "**покрытие** — доля дней, когда факт попал в диапазон low–high (цель 80%); **разрыв найден** — риск с "
             "вероятностью ≥ 50% в пределах ±5 дней от первого дня фактического минуса; **ложная тревога** — риск ≥ 50% там, "
             "где минуса не было.", ""]
    if a:
        lines += ["## А. Демо-компании с известным будущим (data/synthetic)", "",
                  "Прогноз на 30 дней от последней операции (23.10.2026) сравнивается с «как было на самом деле» "
                  "(`data/synthetic/future/`). Источники — тестовые данные из `data/synthetic/integrations/`.", ""]
        dfa = pd.DataFrame(a)
        s02 = dfa[dfa["company"] == "S02"].set_index("config")
        if len(s02):
            lines += ["### Витрина: S02 «Вектор Бизнес-Сервис» (B2B, задержка крупного клиента)", "",
                      f"На самом деле остаток ушёл в минус **{s02['true_gap'].iloc[0]}**, минимум {_fmt_rub(s02['true_min'].iloc[0])}.", "",
                      "| источники | MAE, ₽ | покрытие | вероятность разрыва у факта | разрыв найден |", "|---|---:|---:|---:|:---:|"]
            for cfg in ["base", "tax_calendar", "bank", "1c", "registry", "contracts", "1c+registry", "all"]:
                if cfg in s02.index:
                    r = s02.loc[cfg]
                    lines.append(f"| {TITLES[cfg]} | {_fmt_rub(r['mae'])} | {r['coverage_80']:.0%} | {r['prob_at_true_gap']:.0%} | "
                                 f"{'да' if r['detected'] else 'нет'} |")
            lines.append("")
        lines += ["### Все 5 демо-компаний", "", "| компания | источники | MAE, ₽ | покрытие | факт: минус | p(разрыва) у факта | найден | ложная тревога |",
                  "|---|---|---:|---:|---|---:|:---:|:---:|"]
        for r in a:
            if r["config"] in ("base", "all"):
                lines.append(f"| {r['company']} | {TITLES[r['config']]} | {_fmt_rub(r['mae'])} | {r['coverage_80']:.0%} | "
                             f"{r['true_gap'] or '—'} | {r['prob_at_true_gap']:.0%} | {'да' if r['detected'] else ('—' if not r['true_gap'] else 'нет')} | "
                             f"{'да' if r['false_alarm'] else 'нет'} |")
        checks = [(r["company"], t) for r in a if r.get("tax_check") for t in r["tax_check"]]
        if checks:
            lines += ["", "Точность налогового календаря (оценка ЕНП по выписке против фактического платежа):", "",
                      "| компания | срок | оценка | факт | ошибка |", "|---|---|---:|---:|---:|"]
            for cid, t in checks:
                err = (t["estimate"] / t["actual"] - 1) if t["actual"] else None
                lines.append(f"| {cid} | {t['date']} | {_fmt_rub(t['estimate'])} | {_fmt_rub(t['actual'])} | {_pct(err, True)} |")
            errs = [abs(t["estimate"] / t["actual"] - 1) for _, t in checks if t["actual"]]
            if errs:
                lines += ["", f"Медианная ошибка оценки ЕНП — **{np.median(errs):.0%}**. Там, где налоговый календарь ухудшает MAE "
                              "(S01, S05), сама оценка налога точная, но базовый прогноз ядра уже занижен (в истории — выплаты "
                              "дивидендов и выводы собственных средств, которые модель размазывает по дням)."]
        lines += ["", "Вклад каждого источника по отдельности (5 компаний):", "",
                  "| источники | медиана MAE, ₽ | лучше / хуже / без изменений | изменение MAE там, где изменилось | покрытие | разрывы найдены |",
                  "|---|---:|:---:|---:|---:|---:|"]
        for g in _agg(a, ["base", "tax_calendar", "bank", "1c", "registry", "contracts", "1c+registry", "all"]):
            lines.append(f"| {g['title']} | {_fmt_rub(g['mae_median'])} | {g['n_better']} / {g['n_worse']} / {g['n_same']} | "
                         f"{_pct(g['change_if_changed'], True)} | {g['coverage_80']:.0%} | "
                         f"{'—' if g['gap_recall'] is None else _pct(g['gap_recall'])} из {g['gap_cases']} |")
        lines.append("")
    if b:
        n = len({r['company'] for r in b})
        lines += [f"## Б. Бэктест на реальных выписках организаторов — holdout ({n} компаний)", "",
                  "Только **отложенные компании** (`api/reports/split.py`; единственный параметр источников — доля налогов от "
                  "зарплаты — подобран на dev-компаниях). Отсечка — за 30 дней до последней операции; признаки и события "
                  "считаются только по операциям до отсечки, остатки будущих дней не используются; факт — последние 30 дней. "
                  "**Налоговый календарь** и **банк** (без своего файла — только графики кредитов и лизинга по истории счёта) не используют "
                  "будущее — их вклад честный. **1С (имитация)**: учётная система «знает» ~80% будущих поступлений по "
                  "счетам/договорам с ошибкой даты до ±4 дней — оценка того, сколько даст подключение реальной 1С.", "",
                  "| источники | медиана MAE, ₽ | медиана ошибки, % | лучше / хуже / без изменений | изменение MAE там, где изменилось | покрытие | разрывов найдено | точность сигналов | ложных тревог |",
                  "|---|---:|---:|:---:|---:|---:|---:|---:|---:|"]
        for g in _agg(b, ["base", "tax_calendar", "bank", "tax+bank", "1c_sim", "all_sim"]):
            lines.append(f"| {g['title']} | {_fmt_rub(g['mae_median'])} | {g['mape_median']:.1%} | {g['n_better']} / {g['n_worse']} / {g['n_same']} | "
                         f"{_pct(g['change_if_changed'], True)} | {g['coverage_80']:.0%} | {_pct(g['gap_recall'])} из {g['gap_cases']} | "
                         f"{_pct(g['gap_precision'])} | {g['false_alarms']} |")
        lines += ["", "Выводы по реальным данным:", "",
                  "* налоговый календарь — небольшой выигрыш: даты ЕНП и квартальных авансов известны точно, суммы — оценка;",
                  "* банк без своего файла (графики кредитов по истории) почти не меняет прогноз — ядро и так находит эти платежи;",
                  "* имитация 1С **ухудшает** прогноз: ядро v0.1 добавляет известные поступления по счетам сверх своего "
                  "остаточного ряда выручки (в котором эти же клиенты уже есть) — деньги учитываются дважды. Нужна доработка в "
                  "`core/`: событие от контрагента должно вычитать его долю из остаточного потока (как это уже сделано для "
                  "регулярных платежей в пределах ±7 дней). На демо-компаниях (часть А) выигрыш от 1С есть, потому что "
                  "ключевой клиент — регулярный платёж, и событие его заменяет."]
        lines.append("")
    lines += ["## Как источник влияет на прогноз", "",
              "| источник | что даёт | как учитывается |", "|---|---|---|",
              "| налоговый календарь (`tax_calendar`) | ЕНП до 28-го, авансы УСН, НДС тремя частями, налог на прибыль; режим — из настроек или по выписке | событие `tax` на дату срока (перенос с выходных), сумма — оценка по выписке с расшифровкой в `note`; заменяет налоговый всплеск из истории |",
              "| банк (`bank`) | графики кредитов, ведомости зарплатного проекта, созданные/подписанные платёжки | точные даты и суммы обязательных платежей (`loan`, `payroll`, `contract`/`invoice`) |",
              "| 1С (`1c`) | счета покупателям и от поставщиков, договоры, ведомости | неоплаченный счёт — `expected`/`overdue`; просроченный → ядро закладывает высокую вероятность задержки; платежи, которых нет в истории (годовые лицензии, акты субподрядчиков) |",
              "| договоры (`contracts`) | график, предоплата, отсрочка | события `contract` по графику: предоплата при подписании, остаток после поставки + отсрочка |",
              "| счета (`invoices`) | выставленные/полученные счета с датой и сроком | события `invoice` на срок оплаты на неоплаченный остаток |",
              "| открытые реестры (`registry`) | долги по налогам, суды, ФССП, банкротство контрагента; госконтракты | контрагент с высоким риском → его поступления сдвигаются (сценарий `client_delay` ядра), причина — в `warnings` и `note`; этапы госконтрактов — события `contract` |",
              "| ручной ввод (`manual`) | «клиент обещал 300 000 ₽ 20-го», «в декабре куплю оборудование» | событие `manual` (форма или разбор фразы `/events/parse`) |", "",
              "## Ограничения и что дальше", "",
              "* Если ожидаемую оплату регулярного клиента перенести вручную дальше чем на 7 дней от его обычной даты, "
              "ядро (v0.1) оставляет и регулярный платёж, и событие — деньги учитываются дважды. Для реестров API обходит это "
              "сценарием `client_delay`; для ручного переноса нужна доработка сопоставления событий с регулярными платежами в `core/`.",
              "* Суммы налогов — оценка по выписке: для ОСНО НДС считается по выделенному в назначениях НДС, налог на прибыль — грубо (маржа ≤ 15%).",
              "* Открытые реестры и 1С в прототипе — мок-адаптеры с тестовыми данными; подключение реальных API — замена метода `fetch`/`load`.", ""]
    (OUT / "sources_effect.md").write_text("\n".join(lines), encoding="utf-8")
    (OUT / "sources_effect.json").write_text(json.dumps({"part_a": a, "part_b": b}, ensure_ascii=False, indent=1, default=str),
                                             encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", choices=["A", "B", "AB", "none"], default="AB", help="none — только пересобрать .md из .json")
    ap.add_argument("--companies", type=int, default=100, help="не больше стольких holdout-компаний")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2)))
    ap.add_argument("--n-sims", type=int, default=1000)
    args = ap.parse_args()
    core_path = os.getenv("CORE_PATH", str(ROOT / "core"))
    if core_path not in sys.path:
        sys.path.insert(0, core_path)
    prev = json.loads((OUT / "sources_effect.json").read_text(encoding="utf-8")) if (OUT / "sources_effect.json").exists() else {}
    a = part_a() if "A" in args.part else prev.get("part_a", [])
    b = part_b(args.companies, args.workers, args.n_sims) if "B" in args.part else prev.get("part_b", [])
    write_report(a, b)
    print("→", OUT / "sources_effect.md")


if __name__ == "__main__":
    main()
