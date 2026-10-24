from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .engine import build_state, forecast_from_state
from .fmt import rub
from .taxes import REGIME_LABELS


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Прогноз остатка и кассовых разрывов по выписке")
    ap.add_argument("csv", help="CSV/XLSX выписки (или all_operations.csv вместе с --company)")
    ap.add_argument("--company", default=None, help="company_id, если в файле несколько компаний")
    ap.add_argument("--horizon", type=int, default=30)
    ap.add_argument("--sims", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--scenario", default=None, help='JSON сценария, например \'{"type":"revenue_drop","params":{"percent":20}}\'')
    ap.add_argument("--json", default=None, help="куда сохранить ForecastResult (JSON)")
    a = ap.parse_args(argv)

    if not Path(a.csv).exists():
        print(f"Файл не найден: {a.csv}", file=sys.stderr)
        return 2
    t = time.time()
    st = build_state(a.csv, horizon=a.horizon, company_id=a.company, n_sims=a.sims, seed=a.seed)
    scenario = json.loads(a.scenario) if a.scenario else None
    res = forecast_from_state(st, a.horizon, scenario)
    took = time.time() - t

    print(f"Компания: {res['company_id']}   данные по {st.as_of:%d.%m.%Y}   режим модели: {st.mode}/{st.model_name}")
    print(f"Текущий остаток: {rub(st.start_balance)}")
    regime = st.tax_model.regime or {}
    if regime:
        print(f"Налоговый режим (оценка): {regime.get('label', REGIME_LABELS['unknown'])} "
              f"(уверенность {regime.get('confidence', 0):.0%})")
    print(f"\nПрогноз остатка на {res['horizon_days']} дн. (P10 … медиана … P90):")
    for p in res["daily"][::7] + ([res["daily"][-1]] if (len(res["daily"]) - 1) % 7 else []):
        print(f"  {p['date']}:  {rub(p['balance_low']):>16} … {rub(p['balance_p50']):>16} … {rub(p['balance_high']):>16}")
    print("\nРиски кассового разрыва:")
    if not res["risks"]:
        print("  не найдено (вероятность ниже 5% на всём горизонте)")
    for r in res["risks"]:
        print(f"  [{r['severity'].upper()}] {r['date']}  вероятность {r['probability']:.0%}, нехватка до {rub(r['shortfall_amount'])}")
        print(f"     {r['reason']}")
        for rec in r["recommendations"]:
            print(f"     → {rec}")
    print("\nРегулярные платежи:")
    for r in res["recurring"][:12]:
        sign = "+" if r["direction"] == "in" else "−"
        print(f"  {sign} {r['name']}: {rub(r['amount_avg'])}, следующий {r['next_date']}, уверенность {r['confidence']:.0%}")
    if res["warnings"]:
        print("\nПредупреждения:")
        for w in res["warnings"]:
            print(f"  ! {w}")
    print(f"\n(посчитано за {took:.1f} с, {st.settings['n_sims']} траекторий Monte Carlo, seed={st.settings['seed']})")
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON сохранён: {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
