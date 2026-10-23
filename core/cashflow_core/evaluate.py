"""Проверка качества на любом датасете в формате организаторов.

    python -m cashflow_core.evaluate <папка | CSV> [--workers 4] [--out core/reports]

* ``<папка>`` — папка с ``statements/*.csv`` (или просто с CSV-файлами выписок);
  ``<CSV>`` — один файл: несколько компаний с колонкой ``company_id`` (как
  ``all_operations.csv``) или одна выписка.
* Для каждой компании — rolling-origin бэктест (модель видит только прошлое,
  горизонт 30 дней) трёх подходов и боевой прогноз на последнюю дату (замер скорости).
* Результат: ``<out>/evaluate_<имя>.json`` и ``.md`` — MAE/WAPE остатка, ошибка потоков,
  покрытие интервалов, precision/recall разрывов, срок предупреждения, точность
  регулярных платежей, время на компанию, предупреждения и сбои.

Никакой подгонки под датасет здесь нет: продуктовая конфигурация фиксирована
(в том числе множитель интервалов :data:`schema.INTERVAL_SCALE`, подобранный на
dev-компаниях нашего датасета). Падение на одной компании не останавливает прогон —
оно попадает в отчёт.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .backtest import DEFAULT_MODELS, aggregate, calibrate_interval_scale, metrics_table
from .schema import INTERVAL_SCALE

#: Меняется, когда меняется модель: старый кэш тогда не используется.
CACHE_VERSION = "2026-10-24a"


def discover(path: str | Path) -> list[tuple[str, Any]]:
    """Найти выписки: [(company_id, путь или DataFrame)]."""
    from .io import read_companies

    p = Path(path)
    if p.is_dir():
        d = p / "statements" if (p / "statements").is_dir() else p
        files = sorted(f for f in d.glob("*.csv") if f.name.lower() not in ("companies.csv",))
        if len(files) == 1 and not (p / "statements").is_dir():
            return _split_file(files[0])
        if not files and (p / "all_operations.csv").exists():
            return _split_file(p / "all_operations.csv")
        return [(f.stem, str(f)) for f in files]
    return _split_file(p)


def _split_file(f: Path) -> list[tuple[str, Any]]:
    from .io import read_companies

    parts = read_companies(f)
    if list(parts) == [""]:
        return [(f.stem, str(f))]
    return [(cid, df) for cid, df in parts.items()]


def _fingerprint(src: Any) -> str:
    if isinstance(src, (str, Path)):
        h = hashlib.sha1(Path(src).read_bytes()).hexdigest()
    else:
        h = hashlib.sha1(pd.util.hash_pandas_object(src, index=False).values.tobytes()).hexdigest()
    return h[:16]


def _job(args: tuple[str, Any, dict[str, Any]]) -> dict[str, Any]:
    """Бэктест одной компании + боевой прогноз на последнюю дату (с замером времени)."""
    from . import forecast
    from .backtest import backtest

    cid, src, kw = args
    out: dict[str, Any] = {"company_id": cid}
    t0 = time.time()
    try:
        r = backtest(src, company_id=cid if not isinstance(src, (str, Path)) else None, **kw)
        r.pop("metrics", None)
        out.update(r)
        out["company_id"] = cid
    except Exception as exc:  # noqa: BLE001 — сбой одной компании не должен останавливать прогон
        out.update(error=f"backtest: {type(exc).__name__}", records={}, recurring={})
    out["secs_backtest"] = round(time.time() - t0, 2)
    t1 = time.time()
    try:
        res = forecast(src, [], 30, company_id=cid if not isinstance(src, (str, Path)) else None,
                       n_sims=2000, interval_scale=kw.get("interval_scale"))
        out["forecast_ok"] = bool(res["daily"])
        out["forecast_warnings"] = res["warnings"]
        out["forecast_risks"] = len(res["risks"])
    except Exception as exc:  # noqa: BLE001
        out["forecast_ok"] = False
        out["forecast_warnings"] = [f"исключение: {type(exc).__name__}"]
    out["secs_forecast"] = round(time.time() - t1, 2)
    return out


def run(companies: list[tuple[str, Any]], *, workers: int, cache: Path | None, origins: int = 8, step: int = 21,
        sims: int = 500, seed: int = 42, interval_scale: float | None = None, progress: bool = True
        ) -> list[dict[str, Any]]:
    """Прогнать компании (параллельно, с кэшем по содержимому выписки и настройкам)."""
    kw = {"horizon": 30, "n_origins": origins, "step": step, "n_sims": sims, "seed": seed,
          "models": DEFAULT_MODELS, "interval_scale": INTERVAL_SCALE if interval_scale is None else interval_scale}
    tag = hashlib.sha1(json.dumps({**kw, "v": CACHE_VERSION}, sort_keys=True, default=str).encode()).hexdigest()[:10]
    results, todo = [], []
    for cid, src in companies:
        f = cache / f"{cid}_{_fingerprint(src)}_{tag}.json" if cache else None
        if f is not None and f.exists():
            results.append(json.loads(f.read_text(encoding="utf-8")))
        else:
            todo.append((cid, src, kw, f))
    t0 = time.time()
    if progress:
        print(f"компаний: {len(companies)}, из кэша: {len(results)}, считать: {len(todo)}", flush=True)
    with ProcessPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = {ex.submit(_job, (cid, src, kw)): f for cid, src, kw, f in todo}
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r)
            f = futs[fut]
            if f is not None and not r.get("error"):
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(json.dumps(r), encoding="utf-8")
            if progress:
                print(f"готово {len(results)}/{len(companies)}: {r['company_id']} "
                      f"({r.get('secs_backtest', 0):.0f}+{r.get('secs_forecast', 0):.1f} с, всего {time.time() - t0:.0f} с)",
                      flush=True)
    return sorted(results, key=lambda r: r["company_id"])


def summarize(results: list[dict[str, Any]], wall_secs: float | None = None) -> dict[str, Any]:
    """Метрики по моделям + скорость + устойчивость."""
    ok = [r for r in results if not r.get("error")]
    met = aggregate(ok) if ok else {}
    sb = [r.get("secs_backtest", 0.0) for r in results]
    sf = [r.get("secs_forecast", 0.0) for r in results]
    warn = Counter(w.split(":")[0].split(" — ")[0][:80] for r in results for w in r.get("forecast_warnings", []))
    return {
        "companies": len(results),
        "backtest_failed": [r["company_id"] for r in results if r.get("error")],
        "forecast_failed": [r["company_id"] for r in results if not r.get("forecast_ok", False)],
        "models": met,
        "speed": {"forecast_secs_median": round(float(np.median(sf)), 2) if sf else None,
                  "forecast_secs_max": round(float(np.max(sf)), 2) if sf else None,
                  "backtest_secs_per_company_median": round(float(np.median(sb)), 1) if sb else None,
                  "wall_secs": round(wall_secs, 1) if wall_secs else None},
        "warnings_top": warn.most_common(12),
        "calibration_check": calibrate_interval_scale(ok, "hybrid") if ok else {},
    }


def write_report(summary: dict[str, Any], out: Path, name: str, meta: dict[str, Any]) -> tuple[Path, Path]:
    out.mkdir(parents=True, exist_ok=True)
    js = out / f"evaluate_{name}.json"
    md = out / f"evaluate_{name}.md"
    js.write_text(json.dumps({"meta": meta, **summary}, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [f"# Проверка качества: {name}", "",
             f"{meta['generated_at']} · компаний: {summary['companies']} · интервал ×{meta['interval_scale']} · "
             f"отсечек до {meta['origins']} (шаг {meta['step']} дн.), горизонт 30 дн.", ""]
    if summary["models"]:
        tab = metrics_table(summary["models"])
        lines += [tab.to_markdown() if hasattr(tab, "to_markdown") and _has_tabulate() else "```\n" + tab.to_string() + "\n```", ""]
        rec = summary["models"].get("_recurring", {})
        if rec:
            lines.append(f"Регулярные платежи: пришли в ±3 дня — {rec.get('hit_rate_pm3d')}, ошибка суммы (медиана) — "
                         f"{rec.get('amount_mape_median')}, ожидалось платежей: {rec.get('expected_payments')}.")
    sp = summary["speed"]
    lines += ["", "## Скорость",
              f"* Боевой прогноз одной компании (2000 траекторий): медиана {sp['forecast_secs_median']} с, максимум {sp['forecast_secs_max']} с.",
              f"* Бэктест одной компании (все отсечки, 3 модели): медиана {sp['backtest_secs_per_company_median']} с.",
              f"* Весь прогон: {sp['wall_secs']} с на {meta['workers']} процессах.", "",
              "## Устойчивость",
              f"* Сбои бэктеста: {summary['backtest_failed'] or 'нет'}; сбои прогноза: {summary['forecast_failed'] or 'нет'}.",
              "* Частые предупреждения:"]
    lines += [f"  * {n} × {w}" for w, n in summary["warnings_top"]]
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return js, md


def _has_tabulate() -> bool:
    try:
        import tabulate  # noqa: F401
        return True
    except ImportError:
        return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Проверка качества прогноза на датасете в формате организаторов")
    ap.add_argument("path", help="папка с выписками (statements/*.csv) или CSV-файл")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2)))
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "reports"))
    ap.add_argument("--name", default=None, help="имя отчёта (по умолчанию — имя папки/файла)")
    ap.add_argument("--ids", default=None, help="только эти company_id через запятую")
    ap.add_argument("--origins", type=int, default=8)
    ap.add_argument("--step", type=int, default=21)
    ap.add_argument("--sims", type=int, default=500)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--interval-scale", type=float, default=None, help="по умолчанию — продуктовый INTERVAL_SCALE")
    ap.add_argument("--no-cache", action="store_true")
    a = ap.parse_args(argv)

    comps = discover(a.path)
    if a.ids:
        keep = set(a.ids.split(","))
        comps = [c for c in comps if c[0] in keep]
    if not comps:
        print("Выписки не найдены.")
        return 2
    out = Path(a.out)
    t0 = time.time()
    results = run(comps, workers=a.workers, cache=None if a.no_cache else out / "_cache" / "evaluate",
                  origins=a.origins, step=a.step, sims=a.sims, seed=a.seed, interval_scale=a.interval_scale)
    wall = time.time() - t0
    name = a.name or Path(a.path).stem
    meta = {"generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(), "path": str(a.path),
            "workers": a.workers, "origins": a.origins, "step": a.step, "sims": a.sims, "seed": a.seed,
            "interval_scale": INTERVAL_SCALE if a.interval_scale is None else a.interval_scale,
            "companies": [c for c, _ in comps]}
    summary = summarize(results, wall)
    js, md = write_report(summary, out, name, meta)
    if summary["models"]:
        print(metrics_table(summary["models"]).to_string())
    print(f"\nСкорость: {summary['speed']}\nСбои: бэктест {summary['backtest_failed'] or 'нет'}, "
          f"прогноз {summary['forecast_failed'] or 'нет'}\nОтчёт: {js}, {md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
