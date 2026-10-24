#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent
CORE_DIR = REPO_ROOT / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

import numpy as np

if os.name == "nt":
    os.system("")


class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"


C = Colors
GAP_DEFINITION = "разрыв — остаток на счёте ушёл бы ниже нуля без денег владельца (как в core/reports/metrics.md)"


def log_header(title: str) -> None:
    print(f"\n{C.BOLD}{C.CYAN}{'=' * 78}{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}  {title}{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}{'=' * 78}{C.RESET}\n")


def log_step(step: int, total: int, title: str, started: float | None = None) -> None:
    prefix = f"{C.BOLD}{C.GREEN}[ШАГ {step}/{total}]{C.RESET} {C.BOLD}{C.WHITE}{title}{C.RESET}"
    if started is None:
        print(f"[{datetime.now():%H:%M:%S}] {prefix}")
    else:
        print(f"  {prefix} {C.DIM}(выполнено за {time.time() - started:.2f} сек){C.RESET}")


def fmt_rub(val: float | None) -> str:
    if val is None or not np.isfinite(val):
        return "—"
    return f"{val:,.0f} ₽".replace(",", " ")


def fmt_pct(val: float | None, digits: int = 1) -> str:
    return "—" if val is None else f"{val * 100:.{digits}f} %"


def fmt_num(val: float | None) -> str:
    return "—" if val is None else f"{val:,.0f}".replace(",", " ")


def _backtest_job(args: tuple[str, Any, int, int]) -> dict[str, Any]:
    from cashflow_core.backtest import backtest
    from cashflow_core.schema import INTERVAL_SCALE

    cid, src, horizon, origins = args
    try:
        r = backtest(src, company_id=cid if not isinstance(src, (str, Path)) else None, horizon=horizon,
                     n_origins=origins, models=["hybrid", "flat"], interval_scale=INTERVAL_SCALE,
                     recurring_check=False)
        r.pop("metrics", None)
        r["company_id"] = cid
        return r
    except Exception as exc:
        return {"company_id": cid, "error": type(exc).__name__, "records": {}}


def run_backtests(companies: list[tuple[str, Any]], horizon: int, origins: int, workers: int) -> list[dict[str, Any]]:
    from cashflow_core.parallel import make_pool

    jobs = [(cid, src, horizon, origins) for cid, src in companies]
    if workers <= 1 or len(jobs) == 1:
        return [_backtest_job(j) for j in jobs]
    out = []
    with make_pool(workers) as ex:
        futs = [ex.submit(_backtest_job, j) for j in jobs]
        for k, fut in enumerate(as_completed(futs), 1):
            out.append(fut.result())
            if k % 10 == 0 or k == len(futs):
                print(f"      {C.DIM}готово {k}/{len(futs)}{C.RESET}", flush=True)
    return sorted(out, key=lambda r: r["company_id"])


def _mse(results: list[dict[str, Any]], model: str) -> float | None:
    err = [x["err_vs_actual"] for r in results for x in r["records"].get(model, [])]
    return float(np.mean(np.square(np.array(err)))) if err else None


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None:
        return None
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def compute_metrics(results: list[dict[str, Any]]) -> dict[str, Any] | None:
    from cashflow_core.backtest import aggregate

    ok = [r for r in results if not r.get("error") and r["records"].get("hybrid")]
    if not ok:
        return None
    met = aggregate(ok)
    h, f = met["hybrid"], met.get("flat", {})
    g = h["gaps_without_owner_rescue"]
    tp, fp, fn, tn = g["tp"], g["fp"], g["fn"], g["tn"]
    total = tp + fp + fn + tn
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    mse, mse_flat = _mse(ok, "hybrid"), _mse(ok, "flat")
    return {
        "companies": len(ok),
        "forecasts": h["n_forecasts"],
        "failed": sorted(r["company_id"] for r in results if r.get("error")),
        "no_history": sorted(r["company_id"] for r in results if not r.get("error") and not r["records"].get("hybrid")),
        "gap_definition": GAP_DEFINITION,
        "regression": {
            "mae_rub": h["actual_balance_mae_rub"],
            "mae_pct_turnover": h["actual_balance_mae_pct_turnover"],
            "mse": round(mse, 0) if mse is not None else None,
            "rmse_rub": round(float(np.sqrt(mse)), 0) if mse is not None else None,
            "wape": h["actual_balance_wape"],
            "coverage_p10_p90": h["actual_coverage_p10_p90"],
        },
        "baseline_flat": {
            "mae_rub": f.get("actual_balance_mae_rub"),
            "mae_pct_turnover": f.get("actual_balance_mae_pct_turnover"),
            "mse": round(mse_flat, 0) if mse_flat is not None else None,
            "wape": f.get("actual_balance_wape"),
        },
        "classification": {
            "accuracy": round((tp + tn) / total, 4) if total else None,
            "precision": round(precision, 4) if precision is not None else None,
            "recall": round(recall, 4) if recall is not None else None,
            "f1_score": round(_f1(precision, recall), 4) if _f1(precision, recall) is not None else None,
            "brier_score": g["brier"],
            "confusion_matrix": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        },
    }


def print_report(m: dict[str, Any]) -> None:
    r, b, c = m["regression"], m["baseline_flat"], m["classification"]
    cm = c["confusion_matrix"]
    line = f"{C.BOLD}{C.WHITE}{'=' * 78}{C.RESET}"
    print(f"\n{line}\n{C.BOLD}{C.YELLOW}{'ИТОГОВЫЙ ОТЧЕТ ПО МЕТРИКАМ МОДЕЛИ':^78}{C.RESET}\n{line}")
    print(f"{C.DIM}Бэктест: {m['companies']} компаний, {m['forecasts']} прогнозов «из прошлого» на 30 дней, "
          f"сравнение с фактическим остатком.{C.RESET}")

    print(f"\n{C.BOLD}{C.CYAN}1. ТОЧНОСТЬ ПРОГНОЗА ОСТАТКА (РЕГРЕССИЯ):{C.RESET}")
    print("  ┌──────────────────────────────────────┬────────────────────┬────────────────────┐")
    print("  │ Метрика                              │ Модель             │ «Не изменится»     │")
    print("  ├──────────────────────────────────────┼────────────────────┼────────────────────┤")
    rows = [
        ("MAE, ₽", fmt_rub(r["mae_rub"]), fmt_rub(b["mae_rub"])),
        ("MAE, % месячного оборота (медиана)", fmt_pct(r["mae_pct_turnover"]), fmt_pct(b["mae_pct_turnover"])),
        ("MSE, ₽²", fmt_num(r["mse"]), fmt_num(b["mse"])),
        ("RMSE, ₽", fmt_rub(r["rmse_rub"]), fmt_rub(np.sqrt(b["mse"]) if b["mse"] is not None else None)),
        ("WAPE", fmt_pct(r["wape"]), fmt_pct(b["wape"])),
        ("Покрытие P10..P90 (номинал 80 %)", fmt_pct(r["coverage_p10_p90"]), "—"),
    ]
    for name, a, z in rows:
        print(f"  │ {name:<36} │ {a:>18} │ {z:>18} │")
    print("  └──────────────────────────────────────┴────────────────────┴────────────────────┘")

    print(f"\n{C.BOLD}{C.CYAN}2. ПОИСК КАССОВЫХ РАЗРЫВОВ (КЛАССИФИКАЦИЯ):{C.RESET}")
    print(f"  {C.DIM}{GAP_DEFINITION}; прогноз «разрыв» — вероятность от 50 %.{C.RESET}")
    print("  ┌──────────────────────────────────────┬──────────────────┐")
    print("  │ Метрика                              │ Значение         │")
    print("  ├──────────────────────────────────────┼──────────────────┤")
    for name, val in [("Accuracy", fmt_pct(c["accuracy"])), ("Precision", fmt_pct(c["precision"])),
                      ("Recall", fmt_pct(c["recall"])), ("F1-score", fmt_pct(c["f1_score"])),
                      ("Brier score (0 — идеально)", "—" if c["brier_score"] is None else f"{c['brier_score']:.4f}")]:
        print(f"  │ {name:<36} │ {val:>16} │")
    print("  └──────────────────────────────────────┴──────────────────┘")
    if c["precision"] is None or c["recall"] is None:
        print(f"  {C.YELLOW}«—»: в выборке не было прогнозов или фактов разрыва, метрика не определена.{C.RESET}")

    print(f"\n{C.BOLD}{C.CYAN}3. МАТРИЦА ОШИБОК 2x2:{C.RESET}")
    print("  ┌──────────────────────┬────────────────────────┬────────────────────────┐")
    print("  │                      │ Факт: РАЗРЫВ           │ Факт: НОРМА            │")
    print("  ├──────────────────────┼────────────────────────┼────────────────────────┤")
    print(f"  │ Прогноз: РАЗРЫВ      │ {C.GREEN}TP = {cm['tp']:<17}{C.RESET} │ {C.RED}FP = {cm['fp']:<17}{C.RESET} │")
    print(f"  │ Прогноз: НОРМА       │ {C.RED}FN = {cm['fn']:<17}{C.RESET} │ {C.GREEN}TN = {cm['tn']:<17}{C.RESET} │")
    print("  └──────────────────────┴────────────────────────┴────────────────────────┘")
    print(f"  {C.DIM}Одна клетка — один прогноз «из прошлого»: компания × дата прогноза.{C.RESET}\n")


def print_risks(res: dict[str, Any], horizon: int) -> None:
    from cashflow_core.schema import GAP_PROBABILITY_LIKELY

    risks = res.get("risks") or []
    if not risks:
        print(f"    • {C.BOLD}{C.GREEN}На {horizon} дней риска нехватки денег не видно.{C.RESET}")
        return
    for rk in risks:
        p = float(rk.get("probability") or 0.0)
        if rk.get("kind") == "gap":
            likely = p >= GAP_PROBABILITY_LIKELY
            color = C.RED if likely else C.YELLOW
            head = "КАССОВЫЙ РАЗРЫВ ВЕРОЯТЕН" if likely else "Возможна нехватка денег"
            print(f"    • {C.BOLD}{color}{head}{C.RESET}: {rk.get('date')} · вероятность {color}{p:.0%}{C.RESET} · "
                  f"нехватка, если разрыв случится: {C.BOLD}{fmt_rub(rk.get('shortfall_amount'))}{C.RESET}")
        else:
            print(f"    • {C.YELLOW}Остаток ниже комфортного уровня{C.RESET}: {rk.get('date')} · вероятность {p:.0%}")
        if rk.get("reason"):
            print(f"        Причина: {rk['reason']}")
        recs = rk.get("recommendations") or []
        if recs:
            print(f"        Что сделать: {C.CYAN}{recs[0]}{C.RESET}")


def run_pipeline(dataset_path: Path, horizon: int = 30, target_company: str | None = None,
                 out_dir: Path | None = None, workers: int = 4, origins: int = 4,
                 backtest_limit: int | None = None) -> dict[str, Any]:
    import pandas as pd

    from cashflow_core.categorize import categorize
    from cashflow_core.evaluate import discover
    from cashflow_core.io import load_statement
    from cashflow_core.predict import predict
    from cashflow_core.recurring import detect_recurring

    started = time.time()
    out_dir = out_dir or REPO_ROOT
    out_dir.mkdir(parents=True, exist_ok=True)

    log_header("ФИНАНСОВОЕ ПРОГНОЗИРОВАНИЕ КАССОВЫХ РАЗРЫВОВ | БАНК ЦЕНТР-ИНВЕСТ")
    print(f"{C.DIM}Входной путь:       {C.RESET}{dataset_path}")
    print(f"{C.DIM}Горизонт:           {C.RESET}{horizon} дней")
    print(f"{C.DIM}Целевая компания:   {C.RESET}{target_company or 'первая в датасете'}")
    print(f"{C.DIM}Папка результатов:  {C.RESET}{out_dir}\n")

    t0 = time.time()
    log_step(1, 5, "Загрузка и проверка данных (CSV, UTF-8 BOM / cp1251, колонки, дубли)")
    if not dataset_path.exists():
        raise FileNotFoundError(f"Путь не найден: {dataset_path}")
    companies = discover(dataset_path)
    if target_company:
        companies = [c for c in companies if c[0] == target_company] or companies
    if not companies:
        raise ValueError(f"Не найдено выписок в {dataset_path}")
    frames: dict[str, pd.DataFrame] = {}
    for cid, src in companies:
        frames[cid] = load_statement(src, company_id=cid if not isinstance(src, (str, Path)) else None)
    primary_cid = target_company if target_company in frames else companies[0][0]
    primary = frames[primary_cid]
    dates = pd.to_datetime(primary["date"])
    total_ops = sum(len(df) for df in frames.values())
    print(f"    • Компаний: {C.BOLD}{len(frames)}{C.RESET} (подробно: {C.CYAN}{primary_cid}{C.RESET})")
    print(f"    • Операций всего: {C.BOLD}{total_ops:,}{C.RESET}".replace(",", " "))
    if len(primary):
        print(f"    • Период {primary_cid}: с {C.YELLOW}{dates.min():%Y-%m-%d}{C.RESET} по {C.YELLOW}{dates.max():%Y-%m-%d}{C.RESET}")
    for w in (primary.attrs.get("warnings") or [])[:3]:
        print(f"    • {C.YELLOW}Замечание о данных:{C.RESET} {w}")
    log_step(1, 5, "Загрузка завершена", t0)

    t0 = time.time()
    log_step(2, 5, "Категоризация операций и поиск регулярных платежей")
    cat_df = categorize(primary)
    recurring = detect_recurring(cat_df)
    counts = cat_df["category"].value_counts()
    print(f"    • Категорий: {len(counts)}")
    for name, cnt in list(counts.items())[:4]:
        print(f"      - {name}: {cnt} операций")
    print(f"    • Регулярных платежей (аренда, налоги, зарплата, поставщики): {C.BOLD}{C.CYAN}{len(recurring)}{C.RESET}")
    for r in recurring[:3]:
        sign = "+" if r.get("direction") == "in" else "-"
        print(f"      - {r.get('name')}: {sign}{fmt_rub(r.get('amount_avg'))} каждые ~{r.get('period_days')} дн. "
              f"(след. {r.get('next_date')})")
    log_step(2, 5, "Категоризация завершена", t0)

    t0 = time.time()
    log_step(3, 5, f"Прогноз на {horizon} дней для всех компаний: план платежей + Монте-Карло, 2000 вариантов")
    csv_path, json_path, results = predict(companies, out_dir / "predictions.csv", horizon, workers=workers)
    res = next((x for x in results if x["company_id"] == primary_cid), results[0])
    p50 = [row[2] for row in res["rows"]]
    print(f"    • Текущий остаток {primary_cid}: {C.BOLD}{fmt_rub(res.get('current_balance'))}{C.RESET}")
    print(f"    • Минимальный ожидаемый остаток (P50): {C.BOLD}{C.RED if min(p50) < 0 else C.GREEN}{fmt_rub(min(p50))}{C.RESET}")
    print(f"    • Ожидаемый остаток через {horizon} дней: {C.BOLD}{fmt_rub(p50[-1])}{C.RESET}")
    fallback = [x["company_id"] for x in results if x["status"] != "ok"]
    if fallback:
        print(f"    • {C.YELLOW}Без прогноза (остаток без изменений): {', '.join(fallback)}{C.RESET}")
    log_step(3, 5, "Прогноз построен", t0)

    t0 = time.time()
    log_step(4, 5, "Риски нехватки денег")
    print_risks(res, horizon)
    with_gap = sum(1 for x in results if any(rk.get("kind") == "gap" for rk in x.get("risks") or []))
    if len(results) > 1:
        print(f"    • Компаний с риском разрыва на {horizon} дней: {C.BOLD}{with_gap}{C.RESET} из {len(results)}")
    log_step(4, 5, "Анализ рисков завершен", t0)

    t0 = time.time()
    bt_companies = companies[:backtest_limit] if backtest_limit else companies
    log_step(5, 5, f"Метрики качества: бэктест rolling origin, {len(bt_companies)} компаний × до {origins} отсечек")
    bt = run_backtests(bt_companies, horizon, origins, workers)
    metrics = compute_metrics(bt)
    log_step(5, 5, "Метрики рассчитаны", t0)

    if metrics is None:
        print(f"\n  {C.YELLOW}Метрики не посчитаны: у компаний слишком короткая история для бэктеста.{C.RESET}\n")
    else:
        print_report(metrics)
        if metrics["failed"]:
            print(f"  {C.YELLOW}Бэктест не удался: {', '.join(metrics['failed'])}{C.RESET}")
        if metrics["no_history"]:
            print(f"  {C.DIM}Мало истории для бэктеста: {', '.join(metrics['no_history'])}{C.RESET}")

    metrics_path = out_dir / "checkpoint_metrics.json"
    payload = {"generated_at": datetime.now().isoformat(timespec="seconds"), "dataset": str(dataset_path),
               "horizon_days": horizon, "origins": origins, **(metrics or {"error": "мало истории для бэктеста"})}
    metrics_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{C.BOLD}{C.GREEN}[OK] ФАЙЛЫ СОХРАНЕНЫ:{C.RESET}")
    print(f"  1. {C.WHITE}{csv_path}{C.RESET} ({sum(len(x['rows']) for x in results)} строк)")
    print(f"  2. {C.WHITE}{json_path}{C.RESET}")
    print(f"  3. {C.WHITE}{metrics_path}{C.RESET}")
    print(f"\n{C.BOLD}Общее время работы: {C.CYAN}{time.time() - started:.2f} сек{C.RESET}\n")
    return {"metrics": metrics, "primary_company": primary_cid, "companies_count": len(frames)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Чек-поинт: прогноз остатка, риски и метрики качества")
    ap.add_argument("dataset", help="CSV выписки или папка с датасетом (data/raw, statements/)")
    ap.add_argument("--horizon", type=int, default=30, help="горизонт прогноза в днях (по умолчанию 30)")
    ap.add_argument("--company", default=None, help="компания для подробного показа, например C001")
    ap.add_argument("--out-dir", default=None, help="папка для predictions.csv, predictions.json, checkpoint_metrics.json")
    ap.add_argument("--workers", type=int, default=max(1, min(8, os.cpu_count() or 1)), help="число процессов")
    ap.add_argument("--origins", type=int, default=4, help="отсечек бэктеста на компанию (по умолчанию 4)")
    ap.add_argument("--backtest-limit", type=int, default=None, help="бэктест только по первым N компаниям")
    a = ap.parse_args()
    run_pipeline(Path(a.dataset).resolve(), a.horizon, a.company,
                 Path(a.out_dir).resolve() if a.out_dir else REPO_ROOT, a.workers, a.origins, a.backtest_limit)


if __name__ == "__main__":
    main()
