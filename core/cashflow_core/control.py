"""Имитация проверки на контрольном датасете: последние N дней каждой выписки — «факт».

    python -m cashflow_core.control data/raw [--days 30] [--workers 4] [--split core/reports/split.json]

Для каждой компании из выписки убираются операции за последние ``days`` календарных дней,
по остатку строится прогноз тем же путём, что и в :mod:`predict` (боевая конфигурация,
2000 траекторий), и медиана P50 сравнивается с фактическим ``balance_eod`` (дни без
операций — последний известный остаток). Рядом — бейзлайн «остаток не изменится».

Метрики: MAE (₽), WAPE = Σ|прогноз − факт| / Σ|факт|, медиана WAPE по компаниям, покрытие
P10–P90 и доля компаний, где модель точнее бейзлайна (по MAE). Отдельно для dev и holdout,
если передан ``--split``. Пишет ``<out>/control_<name>.json`` и ``.md``.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .evaluate import discover
from .parallel import make_pool


def _raw_frame(src: Any) -> pd.DataFrame:
    """Выписка как есть (строки и колонки файла), без очистки."""
    if isinstance(src, pd.DataFrame):
        return src.copy()
    from .io import _find_header, _read_any

    raw = _read_any(src)
    return _find_header(raw) if len(raw) else raw


def _until(raw: pd.DataFrame, cut: pd.Timestamp) -> pd.DataFrame:
    """Строки выписки с датой не позже ``cut`` — «выписка, выгруженная на эту дату»."""
    from .io import _match_columns, parse_dates

    col = _match_columns(raw.columns).get("date")
    if col is None:
        return raw
    d, _ = parse_dates(raw[col])
    return raw.loc[d.notna() & (d <= cut)].reset_index(drop=True)


def control_company(cid: str, src: Any, days: int = 30, n_sims: int = 2000, seed: int = 42) -> dict[str, Any]:
    """Прогноз по выписке без последних ``days`` дней и сравнение с фактом."""
    from .io import load_statement, to_daily
    from .predict import predict_company

    full = load_statement(_raw_frame(src), company_id=cid)
    out: dict[str, Any] = {"company_id": cid}
    if len(full) < 2:
        return {**out, "error": "мало операций"}
    daily = to_daily(full)
    last = daily.index[-1]
    cut = last - pd.Timedelta(days=days)
    if cut < daily.index[0]:
        return {**out, "error": "история короче периода проверки"}
    raw = _until(_raw_frame(src), cut)
    # последняя операция в обрезанной выписке может быть раньше cut — берём прогноз с запасом и выравниваем по датам
    res = predict_company(cid, raw, horizon=days + 15, seed=seed, n_sims=n_sims)
    bal = daily["balance_reported"].where(daily["balance_reported"].notna(), daily["balance"])
    idx = pd.date_range(cut + pd.Timedelta(days=1), periods=days, freq="D")
    act = bal.reindex(bal.index.union(idx)).ffill().reindex(idx).values.astype(float)
    b0 = float(bal.loc[:cut].iloc[-1])
    by_date = {r[1]: r for r in res["rows"]}
    rows = [by_date.get(d.date().isoformat()) for d in idx]
    if any(r is None for r in rows):
        return {**out, "error": "прогноз не покрывает период проверки"}
    p50 = np.array([r[2] for r in rows], dtype=float)
    lo = np.array([r[3] for r in rows], dtype=float)
    hi = np.array([r[4] for r in rows], dtype=float)
    turnover = float(daily.loc[:cut].iloc[-30:]["outflow"].sum()) or 1.0
    return {**out, "as_of": str(cut.date()), "status": res["status"], "mode": res.get("mode"), "b0": b0,
            "turnover30": turnover, "actual": act.tolist(), "p50": p50.tolist(), "lo": lo.tolist(), "hi": hi.tolist(),
            "gap_actual": bool((act < 0).any()), "gap_pred_p50": bool((p50 < 0).any()),
            "gap_prob_max": max([float(r["probability"]) for r in res["risks"] if r.get("kind", "gap") == "gap"],
                                default=0.0)}


def _job(args: tuple[str, Any, int, int]) -> dict[str, Any]:
    cid, src, days, n_sims = args
    try:
        return control_company(cid, src, days, n_sims)
    except Exception as exc:  # noqa: BLE001 — одна компания не должна ронять прогон
        return {"company_id": cid, "error": type(exc).__name__}


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [r for r in rows if not r.get("error")]
    if not ok:
        return {"companies": 0}
    act = np.array([r["actual"] for r in ok])
    p50 = np.array([r["p50"] for r in ok])
    flat = np.array([[r["b0"]] * act.shape[1] for r in ok])
    lo, hi = np.array([r["lo"] for r in ok]), np.array([r["hi"] for r in ok])
    turn = np.array([r["turnover30"] for r in ok])[:, None]
    den = np.abs(act).sum(axis=1)

    def block(pred: np.ndarray) -> dict[str, Any]:
        e = np.abs(pred - act)
        per_w = e.sum(axis=1) / np.maximum(den, 1.0)
        return {"mae_rub_mean": round(float(e.mean()), 0), "mae_rub_median_company": round(float(np.median(e.mean(axis=1))), 0),
                "wape": round(float(e.sum() / max(np.abs(act).sum(), 1.0)), 4),
                "wape_median_company": round(float(np.median(per_w)), 4),
                "mae_pct_turnover_median": round(float(np.median((e / turn).mean(axis=1))), 4)}

    m, f = block(p50), block(flat)
    mae_m, mae_f = np.abs(p50 - act).mean(axis=1), np.abs(flat - act).mean(axis=1)
    gaps_a = np.array([r["gap_actual"] for r in ok])
    gaps_p = np.array([r["gap_pred_p50"] for r in ok])
    return {"companies": len(ok), "failed": [r["company_id"] for r in rows if r.get("error")],
            "model": m, "flat": f,
            "coverage_p10_p90": round(float(((act >= lo) & (act <= hi)).mean()), 4),
            "share_model_better": round(float((mae_m < mae_f).mean()), 4),
            "gaps": {"actual": int(gaps_a.sum()), "predicted_p50": int(gaps_p.sum()), "both": int((gaps_a & gaps_p).sum())}}


def _md(name: str, days: int, parts: dict[str, dict[str, Any]], worst: list[tuple[str, float, float]]) -> str:
    lines = [f"# Имитация контрольного датасета: {name}", "",
             f"Последние {days} дней каждой выписки — факт; прогноз строится по остальным операциям (как `predict`), "
             "P50 сравнивается с фактическим `balance_eod`. Бейзлайн — «остаток не изменится».", "",
             "| выборка | компаний | WAPE модели | WAPE «не изменится» | медиана WAPE модели / бейзлайна | MAE модели, ₽ (среднее / медиана) | MAE бейзлайна, ₽ | покрытие P10–P90 | модель точнее |",
             "|---|---|---|---|---|---|---|---|---|"]
    for k, s in parts.items():
        if not s.get("companies"):
            continue
        m, f = s["model"], s["flat"]
        lines.append(f"| {k} | {s['companies']} | {m['wape']:.3f} | {f['wape']:.3f} | {m['wape_median_company']:.3f} / "
                     f"{f['wape_median_company']:.3f} | {m['mae_rub_mean']:,.0f} / {m['mae_rub_median_company']:,.0f} | "
                     f"{f['mae_rub_mean']:,.0f} / {f['mae_rub_median_company']:,.0f} | {s['coverage_p10_p90']:.3f} | "
                     f"{s['share_model_better']:.0%} |".replace(",", " "))
    s = parts.get("все") or next(iter(parts.values()))
    g = s.get("gaps", {})
    lines += ["", f"Разрывы (остаток ниже 0 хотя бы в один день): по факту — {g.get('actual')}, P50 ниже 0 — "
                  f"{g.get('predicted_p50')}, совпало — {g.get('both')}.", "",
              "Наибольшие ошибки (MAE модели / бейзлайна, ₽): " + ", ".join(f"{c} {a:,.0f} / {b:,.0f}".replace(",", " ")
                                                                          for c, a, b in worst)]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Имитация контрольного датасета: последние N дней — факт")
    ap.add_argument("path")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--workers", type=int, default=max(1, min(4, os.cpu_count() or 1)))
    ap.add_argument("--sims", type=int, default=2000)
    ap.add_argument("--split", default=None, help="JSON {dev: [...], holdout: [...]} — метрики по частям")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "reports"))
    ap.add_argument("--name", default=None)
    a = ap.parse_args(argv)
    comps = discover(a.path)
    t0 = time.time()
    jobs = [(cid, src, a.days, a.sims) for cid, src in comps]
    with make_pool(a.workers) as ex:
        rows = sorted(ex.map(_job, jobs), key=lambda r: r["company_id"])
    parts = {"все": summarize(rows)}
    if a.split:
        sp = json.loads(Path(a.split).read_text(encoding="utf-8"))
        for k in ("dev", "holdout"):
            ids = set(sp.get(k, []))
            parts[k] = summarize([r for r in rows if r["company_id"] in ids])
    ok = [r for r in rows if not r.get("error")]
    worst = sorted(((r["company_id"], float(np.mean(np.abs(np.array(r["p50"]) - r["actual"]))),
                     float(np.mean(np.abs(r["b0"] - np.array(r["actual"]))))) for r in ok), key=lambda x: -x[1])[:6]
    name = a.name or Path(a.path).stem
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"control_{name}.json").write_text(json.dumps({"days": a.days, "secs": round(time.time() - t0, 1), "parts": parts,
                                                          "companies": rows}, ensure_ascii=False), encoding="utf-8")
    (out / f"control_{name}.md").write_text(_md(name, a.days, parts, worst), encoding="utf-8")
    print(_md(name, a.days, parts, worst))
    print(f"{time.time() - t0:.0f} с; отчёт: {out / f'control_{name}.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
