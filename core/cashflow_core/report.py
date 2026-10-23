"""Отчёт о качестве для слайда: ``python -m cashflow_core.report``.

Запускает rolling-origin бэктест по стратифицированной (по отраслям) выборке
компаний из ``data/raw``, оценивает категоризацию и сохраняет:

* ``core/reports/metrics.json`` — все метрики и настройки;
* ``core/reports/metrics.md`` — таблица для слайда + методика и оговорки;
* ``core/reports/errors.png`` — ошибка остатка по дням горизонта для каждой модели.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .backtest import DEFAULT_MODELS, aggregate, backtest, calibrate_interval_scale, metrics_table

_COLORS = {"naive": "#eb6834", "ets": "#1baf7a", "hybrid": "#2a78d6"}
_LABELS = {"naive": "Наивная (повтор 28 дней)", "ets": "Сезонная ETS-подобная", "hybrid": "Гибрид (наш)"}


def _one(args: tuple[str, str, dict[str, Any]]) -> dict[str, Any]:
    path, cid, kw = args
    try:
        r = backtest(path, company_id=cid, **kw)
        r.pop("metrics", None)
        return r
    except Exception as exc:  # noqa: BLE001
        return {"company_id": cid, "error": type(exc).__name__, "records": {}, "recurring": {}}


def pick_companies(companies_csv: Path, n: int, seed: int = 42, min_days: int = 240) -> list[str]:
    """Стратифицированная по отраслям выборка компаний с историей ≥ min_days."""
    co = pd.read_csv(companies_csv, sep=";", dtype=str, encoding="utf-8-sig")
    co["days"] = (pd.to_datetime(co["last_operation_date"]) - pd.to_datetime(co["first_operation_date"])).dt.days
    co = co[co["days"] >= min_days]
    rng = np.random.default_rng(seed)
    per = max(1, int(np.ceil(n / co["industry"].nunique())))
    picked = []
    for _, g in co.groupby("industry"):
        idx = rng.permutation(len(g))[:per]
        picked += g.iloc[idx]["company_id"].tolist()
    picked = sorted(picked)
    if len(picked) > n:
        picked = sorted(rng.choice(picked, n, replace=False).tolist())
    return picked


def categorization_report(statements: Path, cids: list[str]) -> dict[str, Any]:
    from .categorize import categorize, classification_metrics, evaluate_categorization
    from .io import load_statement

    cov, acc, f1 = [], [], []
    for cid in cids:
        df = load_statement(statements / f"{cid}.csv")
        ev = evaluate_categorization(df)
        cov.append(ev["coverage_strong_rules"])
        if "ml_holdout_masked_purpose" in ev:
            acc.append(ev["ml_holdout_masked_purpose"]["accuracy"])
            f1.append(ev["ml_holdout_masked_purpose"]["macro_f1"])
    out: dict[str, Any] = {
        "companies": len(cids),
        "strong_rule_coverage_mean": round(float(np.mean(cov)), 4) if cov else None,
        "masked_purpose_holdout_accuracy": round(float(np.mean(acc)), 4) if acc else None,
        "masked_purpose_holdout_macro_f1": round(float(np.mean(f1)), 4) if f1 else None,
    }
    gold_path = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "labeled_purposes.csv"
    if gold_path.exists():
        gold = pd.read_csv(gold_path, sep=";", dtype=str, keep_default_na=False)
        g = pd.DataFrame({"date": pd.Timestamp("2025-09-01"), "amount": 10000.0, "direction": gold["direction"],
                          "counterparty_name": gold["counterparty_name"], "counterparty_inn": "",
                          "purpose": gold["purpose"], "balance_eod": np.nan, "source_id": "",
                          "tx_id": [f"g{i}" for i in range(len(gold))], "signed_amount": 0.0})
        pred = categorize(g)["category"]
        out["independent_gold_set"] = classification_metrics(gold["category"], pred)
    return out


def plot_errors(met: dict[str, Any], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    surface, ink, ink2, grid = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
    fig, ax = plt.subplots(figsize=(9, 4.8), dpi=150)
    fig.patch.set_facecolor(surface)
    ax.set_facecolor(surface)
    ends = []
    for m in ("naive", "ets", "hybrid"):
        if m not in met:
            continue
        y = np.array(met[m]["balance_mae_pct_turnover_by_h"]) * 100
        x = np.arange(1, len(y) + 1)
        ax.plot(x, y, color=_COLORS[m], lw=2, label=_LABELS[m], solid_capstyle="round")
        ends.append([y[-1], x[-1], f"{y[-1]:.0f}%"])
    # разводим подписи на конце линий, чтобы не налезали друг на друга
    ends.sort()
    gap = 1.4
    for i in range(1, len(ends)):
        if ends[i][0] - ends[i - 1][0] < gap:
            ends[i][0] = ends[i - 1][0] + gap
    for ylab, xe, txt in ends:
        ax.annotate(txt, (xe, ylab), xytext=(6, 0), textcoords="offset points", va="center", color=ink2, fontsize=9)
    ax.set_xlabel("День горизонта прогноза", color=ink2)
    ax.set_ylabel("Ошибка остатка, % месячного оборота\n(медиана по прогнозам)", color=ink2)
    ax.set_title("Ошибка прогноза остатка растёт с горизонтом: гибрид держит её ниже", color=ink, loc="left",
                 fontsize=12)
    ax.grid(axis="y", color=grid, lw=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(grid)
    ax.tick_params(colors=ink2)
    ax.set_xlim(1, 32)
    ax.set_ylim(bottom=0)
    leg = ax.legend(frameon=False, loc="upper left")
    for t in leg.get_texts():
        t.set_color(ink)
    fig.tight_layout()
    fig.savefig(path, facecolor=surface)
    plt.close(fig)


def write_markdown(met: dict[str, Any], meta: dict[str, Any], cat: dict[str, Any], path: Path,
                   calib: dict[str, Any] | None = None) -> None:
    tab = metrics_table(met)
    def fmt(v: Any) -> str:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return "—"
        if isinstance(v, float):
            return f"{v:.0%}" if v <= 1.5 else f"{v:.1f}"
        return str(v)
    order = [m for m in ("naive", "ets", "hybrid") if m in tab.index] + [m for m in tab.index if m not in ("naive", "ets", "hybrid")]
    cols = list(tab.columns)
    sp = meta.get("split") or {}
    lines = ["# Качество прогноза — бэктест на отложенных компаниях (holdout)", "",
             f"Компании разделены на dev ({sp.get('dev', '—')}) и holdout ({sp.get('holdout', '—')}): {sp.get('rule', '')}. "
             "Все параметры подбирались только на dev; ниже — метрики **только holdout**.", "",
             "В `metrics.json` (формат контракта) поле `mape` — медианная ошибка остатка в долях месячного оборота, "
             "`mae` — средняя абсолютная ошибка остатка в ₽, `coverage_80` — доля дней, где факт внутри P10–P90.", "",
             f"Сформировано {meta['generated_at']}. Компаний: {meta['n_companies']}, прогнозов на модель: "
             f"{tab['Прогнозов'].max()}, горизонт {meta['horizon']} дн., отсечек на компанию до {meta['n_origins']} "
             f"(шаг {meta['step']} дн.), Monte Carlo {meta['n_sims']} траекторий, seed {meta['seed']}.", "",
             "| Модель | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    for m in order:
        lines.append(f"| {_LABELS.get(m, m)} | " + " | ".join(
            (f"{tab.loc[m, c]:.3f}" if c == "Brier" and tab.loc[m, c] is not None else fmt(tab.loc[m, c])) for c in cols) + " |")
    rec = met.get("_recurring", {})
    g = met.get("hybrid", {}).get("gaps_without_owner_rescue", {})
    ga = met.get("hybrid", {}).get("gaps_actual_balance", {})
    lines += ["", "## Регулярные платежи",
              f"Ожидаемых платежей в горизонте: {rec.get('expected_payments', '—')}; пришли в ±3 дня от предсказанной даты: "
              f"**{fmt(rec.get('hit_rate_pm3d'))}**; медианная ошибка суммы: {fmt(rec.get('amount_mape_median'))}.", "",
              "## Категоризация",
              f"* Правила уверенно размечают {fmt(cat.get('strong_rule_coverage_mean'))} операций "
              f"({cat.get('companies')} компаний).",
              f"* Скрытое назначение платежа (имитация пустого поля) → память контрагента + ML: accuracy "
              f"{fmt(cat.get('masked_purpose_holdout_accuracy'))}, macro-F1 {fmt(cat.get('masked_purpose_holdout_macro_f1'))}."]
    gold = cat.get("independent_gold_set")
    if gold:
        lines.append(f"* Ручная разметка ({gold['n']} назначений в формулировках других банков, не из датасета): accuracy "
                     f"{fmt(gold['accuracy'])}, macro-F1 {fmt(gold['macro_f1'])}. Оговорка: разметку писал тот же автор, что и "
                     "правила, поэтому оценка оптимистична; самая честная цифра — проверка со скрытым назначением выше.")
    lines += ["", "## Разрывы (гибрид)",
              f"* По остатку без «спасательных» пополнений владельца: TP {g.get('tp')}, FP {g.get('fp')}, FN {g.get('fn')}, "
              f"TN {g.get('tn')}; precision {fmt(g.get('precision'))}, recall {fmt(g.get('recall'))}, "
              f"предупреждение в среднем за {g.get('lead_days_mean', '—')} дн., ошибка даты (медиана) "
              f"{g.get('date_error_days_median', '—')} дн., Brier {g.get('brier', '—')}.",
              f"* По фактическому остатку: TP {ga.get('tp')}, FP {ga.get('fp')}, FN {ga.get('fn')}, TN {ga.get('tn')}.",
              ""]
    if calib and calib.get("k"):
        lines += ["## Калибровка интервалов",
                  f"Множитель ширины интервала гибрида k = **{calib['k']}** подобран только на dev-компаниях "
                  f"({calib.get('n_dev_companies')}): покрытие P10–P90 на dev {fmt(calib.get('dev_coverage_before'))} → "
                  f"{fmt(calib.get('dev_coverage_after'))}. Цифры выше — holdout-компании, которые при подборе не использовались, "
                  "в продуктовой конфигурации с этим k.", ""]
    lines += ["## Методика и оговорки",
              "* Rolling origin: на каждой дате отсечения модель обучается только на прошлом (категории, регулярные "
              "платежи, налоги, модели потоков), прогноз на 30 дней сравнивается с фактом.",
              "* Цель для всех моделей одна — остаток **без** пополнений собственными средствами и займов "
              "учредителя/банка (их владелец делает, когда денег не хватает; продукт показывает разрыв до такого спасения).",
              "* Ошибка нормирована на месячный оборот (сумма списаний за 30 дней до отсечки): WAPE остатка "
              "неустойчив, когда остаток близок к нулю.",
              "* Интервал P10–P90: номинальное покрытие 80%. Интервалы всех моделей строятся одинаково — "
              "по эмпирическим ошибкам прошлых прогнозов.",
              "* Разрыв = остаток < 0 хотя бы в один день горизонта; прогноз разрыва = вероятность ≥ 50% хотя бы в один "
              "день. Отсечки, где остаток уже отрицательный, в метрики разрывов не входят.",
              "* Данные синтетические (организаторы), правила категоризации настраивались на их формулировках — поэтому "
              "приведена и независимая ручная разметка.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


_CONTRACT_NAMES = {"naive": "Наивная (повтор последних 28 дней)", "ets": "Сезонная (ETS-подобная)",
                   "hybrid": "Регулярные платежи + налоги + события + Монте-Карло"}


def demo_series(path: Path, company_id: str, horizon: int = 30, n_sims: int = 1000, seed: int = 42) -> list[dict[str, Any]]:
    """Ряд «факт vs прогноз» с последней отсечки бэктеста одной компании — для графика на слайде."""
    from .backtest import _actual, _hybrid
    from .categorize import categorize
    from .io import load_statement, to_daily

    tx = load_statement(path, company_id=company_id)
    tx.attrs = {}
    daily = to_daily(tx)
    origin = (daily.index[-1] - pd.Timedelta(days=horizon)).date()
    fc = _hybrid(tx, origin, horizon, n_sims, seed, "auto")
    act = _actual(daily, categorize(tx), origin, horizon)
    q = np.quantile(fc.balances, [0.1, 0.5, 0.9], axis=0)
    dates = pd.date_range(pd.Timestamp(origin) + pd.Timedelta(days=1), periods=horizon, freq="D")
    return [{"date": d.date().isoformat(), "actual": round(float(a), 2), "predicted": round(float(p), 2),
             "low": round(float(lo), 2), "high": round(float(hi), 2)}
            for d, a, p, lo, hi in zip(dates, act["need"], q[1], q[0], q[2])]


def contract_metrics(met: dict[str, Any], meta: dict[str, Any], series: list[dict[str, Any]]) -> dict[str, Any]:
    """metrics.json строго по разделу 5 контракта.

    ``mape`` здесь — медианная ошибка остатка в долях месячного оборота (MAPE самого остатка
    неустойчив около нуля); пояснение — в metrics.md.
    """
    models = []
    for m in ("naive", "ets", "hybrid"):
        if m not in met:
            continue
        v = met[m]
        g = v["gaps_without_owner_rescue"]
        models.append({"name": _CONTRACT_NAMES[m], "mae": v["balance_mae_rub"], "mape": v["balance_mae_pct_turnover"],
                       "coverage_80": v["coverage_p10_p90"], "gap_recall": g["recall"] or 0.0,
                       "gap_precision": g["precision"] or 0.0, "is_selected": m == "hybrid"})
    return {"generated_at": meta["generated_at"],
            "dataset": f"Датасет организаторов: {meta['n_companies']} компаний, rolling-origin {meta['n_origins']} отсечек "
                       f"× {meta['horizon']} дн.; ряд backtest — {meta.get('demo_company', '')}",
            "horizon_days": meta["horizon"], "models": models, "backtest": series}


def write_all(detail: dict[str, Any], out: Path, data: Path | None = None) -> None:
    """Записать metrics_detail.json, metrics.json (контракт), metrics.md и errors.png."""
    met, meta, cat = detail["models"], detail["meta"], detail["categorization"]
    series = detail.get("demo_series") or []
    if not series and data is not None:
        demo = meta.get("demo_company") or "C001"
        meta["demo_company"] = demo
        series = demo_series(data / "statements" / f"{demo}.csv", demo, meta["horizon"])
        detail["demo_series"] = series
    (out / "metrics_detail.json").write_text(json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "metrics.json").write_text(json.dumps(contract_metrics(met, meta, series), ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    write_markdown(met, meta, cat, out / "metrics.md", detail.get("calibration"))
    plot_errors(met, out / "errors.png")


def make_split(companies_csv: Path, seed: int = 42) -> dict[str, Any]:
    """Разделить компании на dev (подбор параметров) и holdout (финальные метрики) 50/50 внутри каждой отрасли.

    Порядок внутри отрасли задаётся хэшем (seed + company_id) — воспроизводимо и без выбора «удобных» компаний.
    """
    import hashlib

    co = pd.read_csv(companies_csv, sep=";", dtype=str, encoding="utf-8-sig")
    dev, hold = [], []
    for _, g in co.groupby("industry"):
        ids = sorted(g["company_id"], key=lambda c: hashlib.sha1(f"{seed}:{c}".encode()).hexdigest())
        dev += ids[0::2]
        hold += ids[1::2]
    return {"seed": seed, "rule": "50/50 внутри каждой отрасли, порядок по sha1(seed:company_id)",
            "dev": sorted(dev), "holdout": sorted(hold)}


def _load_split(out: Path, data: Path, seed: int) -> dict[str, Any]:
    f = out / "split.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    sp = make_split(data / "companies.csv", seed)
    out.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(sp, ensure_ascii=False, indent=2), encoding="utf-8")
    return sp


def main(argv: list[str] | None = None) -> int:
    """Внутренний конвейер оценки на датасете организаторов.

    1. ``split``     — разделить компании на dev / holdout (``core/reports/split.json``);
    2. ``calibrate`` — бэктест dev-компаний «сырой» моделью, подбор множителя интервалов
                       (``core/reports/calibration.json``); его вносят в ``schema.INTERVAL_SCALE``;
    3. ``final``     — бэктест holdout-компаний в продуктовой конфигурации → ``metrics.json``
                       (формат контракта), ``metrics.md``, ``errors.png``, ``metrics_detail.json``;
    4. ``rebuild``   — пересобрать файлы отчёта из ``metrics_detail.json``.
    """
    from .evaluate import run, summarize, write_report
    from .schema import INTERVAL_SCALE

    ap = argparse.ArgumentParser(description="Оценка качества: dev/holdout")
    ap.add_argument("step_name", choices=["split", "calibrate", "final", "rebuild"])
    ap.add_argument("--data", default="data/raw", help="папка с statements/ и companies.csv")
    ap.add_argument("--origins", type=int, default=8)
    ap.add_argument("--step", type=int, default=21)
    ap.add_argument("--sims", type=int, default=500)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2)))
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "reports"))
    ap.add_argument("--demo-company", default=None, help="holdout-компания для ряда backtest в metrics.json")
    a = ap.parse_args(argv)
    data, out = Path(a.data), Path(a.out)
    cache = out / "_cache" / "evaluate"

    if a.step_name == "rebuild":
        detail = json.loads((out / "metrics_detail.json").read_text(encoding="utf-8"))
        write_all(detail, out, data)
        print(metrics_table(detail["models"]).to_string())
        return 0

    sp = _load_split(out, data, a.seed)
    if a.step_name == "split":
        print(f"dev: {len(sp['dev'])}, holdout: {len(sp['holdout'])} → {out / 'split.json'}")
        return 0

    group = "dev" if a.step_name == "calibrate" else "holdout"
    comps = [(c, str(data / "statements" / f"{c}.csv")) for c in sp[group]]
    scale = 1.0 if group == "dev" else INTERVAL_SCALE
    t0 = time.time()
    results = run(comps, workers=a.workers, cache=cache, origins=a.origins, step=a.step, sims=a.sims, seed=a.seed,
                  interval_scale=scale)
    wall = time.time() - t0
    summary = summarize(results, wall)
    meta = {"generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(), "group": group,
            "n_companies": len(comps), "companies": [c for c, _ in comps], "horizon": 30, "n_origins": a.origins,
            "step": a.step, "n_sims": a.sims, "seed": a.seed, "interval_scale": scale, "workers": a.workers,
            "runtime_sec": round(wall, 1), "failed": summary["backtest_failed"]}
    write_report(summary, out, group, {**meta, "origins": a.origins})

    if group == "dev":
        ok = [r for r in results if not r.get("error")]
        from .backtest import _coverage_with_scale, calibrate_on
        cal = calibrate_interval_scale(ok, "hybrid")
        k_dev = calibrate_on(ok, "hybrid")
        cal_all = {"k": k_dev, "source": "dev", "n_dev_companies": len(comps),
                   "dev_coverage_before": _coverage_with_scale(ok, 1.0),
                   "dev_coverage_after": _coverage_with_scale(ok, k_dev),
                   "time_split_check": cal}
        (out / "calibration.json").write_text(json.dumps(cal_all, ensure_ascii=False, indent=2), encoding="utf-8")
        print(metrics_table(summary["models"]).to_string())
        print(f"\nk = {cal_all['k']} (покрытие dev {cal_all['dev_coverage_before']} → {cal_all['dev_coverage_after']}); "
              f"внесите его в schema.INTERVAL_SCALE. Время: {summary['speed']}")
        return 0

    ok = [r for r in results if not r.get("error")]
    cal = json.loads((out / "calibration.json").read_text(encoding="utf-8")) if (out / "calibration.json").exists() else {}
    cat = categorization_report(data / "statements", [c for c, _ in comps])
    per_company = {}
    for r in ok:
        m1 = aggregate([r])
        per_company[r["company_id"]] = {k: {"mae_pct_turnover": v["balance_mae_pct_turnover"],
                                            "coverage": v["coverage_p10_p90"]} for k, v in m1.items() if not k.startswith("_")}
    demo = a.demo_company or next((c for c in ("C001",) if c in sp["holdout"]), None) or \
        max(ok, key=lambda r: len(r["records"].get("hybrid", [])))["company_id"]
    meta.update(demo_company=demo, split={"dev": len(sp["dev"]), "holdout": len(sp["holdout"]), "rule": sp["rule"]},
                speed=summary["speed"])
    write_all({"meta": meta, "models": summary["models"], "categorization": cat, "per_company": per_company,
               "calibration": cal}, out, data)
    print(metrics_table(summary["models"]).to_string())
    print(f"\nholdout: {len(comps)} компаний, {summary['speed']}; сбои: {summary['backtest_failed'] or 'нет'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
