"""Риски кассового разрыва из симуляций (п.5 задания).

* вероятность разрыва в день t = доля траекторий, где остаток < порога;
* эпизод = подряд идущие дни с вероятностью ≥ :data:`schema.GAP_PROBABILITY_REPORT`
  (эпизоды с перерывом ≤ 2 дней склеиваются);
* ``date`` — первый день эпизода, где разрыв вероятнее, чем нет (p ≥ 0.5),
  иначе день максимальной вероятности;
* ``shortfall_amount`` — P90 максимальной нехватки за эпизод среди траекторий,
  где разрыв случился: «сколько денег нужно, чтобы закрыть разрыв в 9 случаях из 10»;
* ``reason`` и ``recommendations`` — простым языком, по крупнейшим платежам рядом с датой.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import numpy as np

from .fmt import day_month, plural_days, rub
from .schema import GAP_PROBABILITY_LIKELY, GAP_PROBABILITY_REPORT

if TYPE_CHECKING:
    from .engine import ForecastState, Plan, PlannedItem, SimResult

_ACCUSATIVE = {
    "payroll": "зарплату",
    "taxes": "налоги",
    "rent": "аренду",
    "loans": "платёж по кредиту",
    "utilities": "коммунальные платежи и связь",
    "bank_fees": "банковские комиссии",
    "suppliers": "поставщику",
    "other": "платёж",
}


def _what(it: "PlannedItem") -> str:
    if it.kind == "tax":
        return "квартальный налог (ЕНП)"
    if it.kind == "event" and it.category == "other":
        return f"«{it.name}»"
    base = _ACCUSATIVE.get(it.category, "платёж")
    if it.category == "suppliers" and it.counterparty:
        return f"поставщику {it.counterparty}"
    return base


def _episodes(p: np.ndarray, min_p: float, merge_gap: int = 2) -> list[tuple[int, int]]:
    idx = np.nonzero(p >= min_p)[0]
    if not len(idx):
        return []
    eps = [[idx[0], idx[0]]]
    for i in idx[1:]:
        if i - eps[-1][1] <= merge_gap + 1:
            eps[-1][1] = i
        else:
            eps.append([i, i])
    return [(int(a), int(b)) for a, b in eps]


def severity(prob: float, days_until: int) -> str:
    """high: p ≥ 0.6 или (p ≥ 0.4 и ≤ 7 дней); medium: p ≥ 0.25; иначе low."""
    if prob >= 0.6 or (prob >= 0.4 and days_until <= 7):
        return "high"
    if prob >= 0.25:
        return "medium"
    return "low"


def gap_summary(plan: "Plan", sim: "SimResult", threshold: float) -> dict[str, Any]:
    """Вероятности по дням, первая вероятная дата разрыва, P90 максимальной нехватки."""
    bal = sim.balances
    p = (bal < threshold).mean(axis=0)
    deficit = np.maximum(threshold - bal, 0).max(axis=1)
    first = np.nonzero(p >= GAP_PROBABILITY_LIKELY)[0]
    return {
        "prob_by_day": p,
        "first_gap_day": int(first[0]) if len(first) else None,
        "first_gap_date": plan.dates[int(first[0])].isoformat() if len(first) else None,
        "max_shortfall": round(float(np.quantile(deficit, 0.9)), 2),
        "any_gap_prob": float((deficit > 0).mean()),
    }


def find_risks(state: "ForecastState", plan: "Plan", sim: "SimResult") -> list[dict[str, Any]]:
    """Список рисков в формате контракта."""
    thr = float(state.settings.get("threshold", 0.0))
    bal = sim.balances
    H = plan.horizon
    p = (bal < thr).mean(axis=0)
    p50 = np.median(bal, axis=0)
    p10 = np.quantile(bal, 0.1, axis=0)
    risks = []
    for a, b in _episodes(p, GAP_PROBABILITY_REPORT):
        seg = p[a:b + 1]
        likely = np.nonzero(seg >= GAP_PROBABILITY_LIKELY)[0]
        k = a + (int(likely[0]) if len(likely) else int(seg.argmax()))
        prob = float(seg.max())
        deficit = np.maximum(thr - bal[:, a:b + 1], 0).max(axis=1)
        hit = deficit[deficit > 0]
        shortfall = float(np.quantile(hit, 0.9)) if len(hit) else 0.0
        d = plan.dates[k]
        reason = _reason(state, plan, k, a, b, p50, p10, prob, thr)
        recs = _recommendations(state, plan, k, a, b, shortfall)
        risks.append({
            "date": d.isoformat(),
            "shortfall_amount": round(shortfall, 2),
            "probability": round(min(1.0, max(0.0, prob)), 3),
            "severity": severity(prob, k + 1),
            "reason": reason,
            "recommendations": recs,
        })
    return risks


def _reason(state: "ForecastState", plan: "Plan", k: int, a: int, b: int, p50: np.ndarray, p10: np.ndarray,
            prob: float, thr: float) -> str:
    d = plan.dates[k]
    prob_txt = f"Вероятность — около {round(prob * 100 / 5) * 5:.0f}%."
    if k == 0 and plan.start_balance < thr:
        txt = f"Остаток уже ниже нуля ({rub(plan.start_balance)}) — счёт в овердрафте."
        if state.hist_min_balance < 0:
            lim = state.hist_min_balance
            txt += f" Исторический минимум {rub(lim)} похож на лимит овердрафта."
        return txt + " " + prob_txt
    window = [it for it in plan.items if it.direction == "out" and k - 3 <= it.day + it.day_shift <= k]
    window.sort(key=lambda it: -it.expected_amount)
    big = [it for it in window if it.expected_amount >= 0.1 * max(1.0, abs(p50[k] - thr))][:2] or window[:1]
    before = p50[k - 1] if k > 0 else plan.start_balance
    if big:
        pays = " и ".join(f"{_what(it)} {rub(it.expected_amount)}" for it in big)
        if prob >= GAP_PROBABILITY_LIKELY:
            if before > thr:
                txt = f"{day_month(d)} нужно заплатить {pays}, а к этому дню на счёте ожидается около {rub(before)}."
            else:
                txt = f"{day_month(d)} нужно заплатить {pays}, а денег на счёте к этому дню, скорее всего, уже не останется."
        else:
            txt = (f"{day_month(d)} нужно заплатить {pays}. Обычно денег хватает (к этому дню ожидается около "
                   f"{rub(before)}), но если поступления будут ниже обычного, остаток может уйти в минус.")
    else:
        txt = (f"Расходы в ближайшие {plural_days(k + 1)} больше поступлений: к {day_month(d)} остаток "
               f"может опуститься до {rub(min(p10[k], p50[k]))}.")
    gap_size = max(1.0, abs(min(p10[k], p50[k]) - thr))
    late = [it for it in plan.items if it.direction == "in" and it.delay_prob >= 0.15 and k - 14 <= it.day <= k
            and it.counterparty and it.expected_amount >= 0.2 * gap_size]
    if late:
        it = max(late, key=lambda x: x.expected_amount)
        txt += f" Если {it.counterparty} заплатит позже ({rub(it.expected_amount)} ожидается {day_month(plan.dates[min(it.day, plan.horizon - 1)])}), нехватка будет больше."
    return txt + " " + prob_txt


def _round_up(x: float) -> float:
    if x <= 0:
        return 0.0
    step = 10_000 if x < 1_000_000 else 100_000
    return math.ceil(x / step) * step


def _recommendations(state: "ForecastState", plan: "Plan", k: int, a: int, b: int, shortfall: float) -> list[str]:
    recs: list[str] = []
    d = plan.dates[k]
    end_ep = plan.dates[b] + timedelta(days=1)
    # 1. ускорить оплату от клиента
    incoming = [it for it in plan.items if it.direction == "in" and it.counterparty and it.category == "revenue"
                and k - 5 <= it.day + it.day_shift <= k + 21]
    if incoming:
        it = max(incoming, key=lambda x: x.expected_amount)
        when = plan.dates[min(it.day + it.day_shift, plan.horizon - 1)]
        recs.append(f"Попросить {it.counterparty} оплатить {rub(it.expected_amount)} до {day_month(d)} "
                    f"(сейчас оплата ожидается {day_month(when)}).")
    # 2. перенести переносимый платёж
    movable = [it for it in plan.items if it.direction == "out" and it.movable and a - 3 <= it.day + it.day_shift <= b]
    payroll_near = any(it.category == "payroll" and a - 3 <= it.day + it.day_shift <= b for it in plan.items)
    if movable:
        it = max(movable, key=lambda x: x.expected_amount)
        what = f"оплату {_what(it)}" if it.category == "suppliers" else _what(it)
        who = f" — договориться с {it.counterparty}" if it.counterparty else ""
        txt = f"Перенести {what} ({rub(it.expected_amount)}) на {day_month(end_ep)} или позже{who}."
        if payroll_near:
            txt += " Зарплату переносить нельзя (ст. 136 ТК РФ), поэтому сдвигать лучше именно такие платежи."
        recs.append(txt)
    # 3. овердрафт / кредитная линия
    if shortfall > 0 and plan.start_balance < 0:
        recs.append(f"Счёт уже в овердрафте: согласовать с банком лимит не меньше {rub(_round_up(shortfall))} "
                    "или вернуть деньги со счетов в других банках.")
    elif shortfall > 0:
        days = max(3, (b - a) + 3)
        recs.append(f"Заранее подключить овердрафт или кредитную линию примерно на {rub(_round_up(shortfall))} "
                    f"на {plural_days(days)}.")
    # 4. предоплата — запасной вариант
    if len(recs) < 2:
        recs.append("Запросить предоплату у клиентов по новым заказам и выставить счета пораньше.")
    if len(recs) < 2:
        recs.append("Отложить необязательные покупки до прихода денег от клиентов.")
    return recs[:3]
