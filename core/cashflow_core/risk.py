"""Риски для владельца бизнеса (п.5 задания).

Два уровня риска, оба из одних и тех же симуляций:

1. **Кассовый разрыв** — остаток уходит ниже нуля (``threshold``, по умолчанию 0 ₽):
   денег не хватит на платежи, в том числе обязательные (зарплата, налоги, аренда, кредит).
2. **Ниже подушки безопасности** — остаток опускается ниже минимального комфортного
   остатка владельца (``comfort_balance``; по умолчанию — расходы примерно за 7 дней).
   Платежи проходят, но запаса почти нет. Такой риск показывается, только если в эти
   дни нет риска разрыва.

Для каждого риска:

* ``date`` — первый день, когда событие вероятнее, чем нет (p ≥ 0.5), иначе день максимальной вероятности;
* ``probability`` — максимальная за эпизод доля траекторий ниже порога;
* ``shortfall_amount`` — сколько денег нужно, чтобы закрыть нехватку в 9 случаях из 10 (P90 среди
  траекторий, где она случилась);
* ``reason`` — что случится, когда, на какую сумму и почему, с источником каждой суммы;
* ``recommendations`` — 2–3 варианта действий, доступных владельцу.
"""
from __future__ import annotations

import math
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import numpy as np

from .fmt import day_month, plural_days, rub
from .schema import GAP_PROBABILITY_LIKELY, GAP_PROBABILITY_REPORT

if TYPE_CHECKING:
    from .engine import ForecastState, Plan, PlannedItem, SimResult

#: С какой вероятности показывать риск «ниже подушки» (ниже — шум, а не предупреждение).
COMFORT_PROBABILITY_REPORT = 0.25
#: Обязательные платежи: их переносить нельзя или очень дорого.
MANDATORY = ("payroll", "taxes", "loans", "rent")

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

SOURCE_LABELS = {
    "bank": "из выписки",
    "1c": "из 1С",
    "tax_calendar": "налоговый календарь",
    "manual": "вы ввели",
    "open_registry": "из открытых реестров",
}


def source_label(it: "PlannedItem") -> str:
    """Откуда взялась сумма — простыми словами."""
    if it.ref == "scenario":
        return "сценарий"
    if it.kind == "tax":
        return "оценка по выписке и налоговому календарю"
    if it.kind == "recurring":
        return "регулярный платёж из выписки"
    return SOURCE_LABELS.get(it.source, "вы ввели")


def _what(it: "PlannedItem") -> str:
    if it.kind == "tax":
        return "налоги за квартал (ЕНП)"
    if it.kind == "event" and it.category == "other":
        return f"«{it.name}»"
    if it.category == "suppliers" and it.counterparty:
        return f"поставщику {it.counterparty}"
    return _ACCUSATIVE.get(it.category, "платёж")


def _pay(it: "PlannedItem") -> str:
    return f"{_what(it)} {rub(it.expected_amount)} ({source_label(it)})"


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
    """Кассовый разрыв: high — p ≥ 0.6 или (p ≥ 0.4 и ≤ 7 дней); medium — p ≥ 0.25; иначе low."""
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


def _episode_stats(bal: np.ndarray, p: np.ndarray, level: float, a: int, b: int) -> tuple[int, float, float]:
    seg = p[a:b + 1]
    likely = np.nonzero(seg >= GAP_PROBABILITY_LIKELY)[0]
    k = a + (int(likely[0]) if len(likely) else int(seg.argmax()))
    deficit = np.maximum(level - bal[:, a:b + 1], 0).max(axis=1)
    hit = deficit[deficit > 0]
    return k, float(seg.max()), float(np.quantile(hit, 0.9)) if len(hit) else 0.0


def find_risks(state: "ForecastState", plan: "Plan", sim: "SimResult", with_kind: bool = False) -> list[dict[str, Any]]:
    """Список рисков в формате контракта, по дате.

    ``with_kind=True`` добавляет поле ``kind``: ``"gap"`` (остаток < 0) или ``"below_comfort"``
    (ниже подушки безопасности) — для машинного вывода :mod:`predict`; в ответе API его нет.
    """
    thr = float(state.settings.get("threshold", 0.0))
    comfort = float(state.settings.get("comfort_balance") or 0.0)
    bal = sim.balances
    p50 = np.median(bal, axis=0)
    p10 = np.quantile(bal, 0.1, axis=0)
    risks: list[tuple[int, dict[str, Any]]] = []

    p_gap = (bal < thr).mean(axis=0)
    gap_days: set[int] = set()
    for a, b in _episodes(p_gap, GAP_PROBABILITY_REPORT):
        gap_days.update(range(a, b + 1))
        k, prob, shortfall = _episode_stats(bal, p_gap, thr, a, b)
        risks.append((k, {
            "kind": "gap",
            "date": plan.dates[k].isoformat(),
            "shortfall_amount": round(shortfall, 2),
            "probability": round(min(1.0, max(0.0, prob)), 3),
            "severity": severity(prob, k + 1),
            "reason": _gap_reason(state, plan, k, p50, p10, prob, thr, b, shortfall),
            "recommendations": _recommendations(state, plan, k, a, b, shortfall, gap=True),
        }))

    if comfort > thr:
        p_c = (bal < comfort).mean(axis=0)
        for a, b in _episodes(p_c, COMFORT_PROBABILITY_REPORT):
            if any(d in gap_days for d in range(a, b + 1)):
                continue  # в эти дни уже есть риск разрыва — он важнее
            k, prob, shortfall = _episode_stats(bal, p_c, comfort, a, b)
            risks.append((k, {
                "kind": "below_comfort",
                "date": plan.dates[k].isoformat(),
                "shortfall_amount": round(shortfall, 2),
                "probability": round(min(1.0, max(0.0, prob)), 3),
                "severity": "medium" if prob >= 0.6 and k < 7 else "low",
                "reason": _comfort_reason(state, plan, k, p50, prob, comfort),
                "recommendations": _recommendations(state, plan, k, a, b, shortfall, gap=False),
            }))
    risks.sort(key=lambda kr: kr[0])
    if not with_kind:
        for _, r in risks:
            r.pop("kind", None)
    return [r for _, r in risks]


def _prob_text(prob: float) -> str:
    return f"Вероятность — около {round(prob * 100 / 5) * 5:.0f}%."


def _due_items(plan: "Plan", k: int) -> list["PlannedItem"]:
    window = [it for it in plan.items if it.direction == "out" and k - 3 <= it.day + it.day_shift <= k]
    return sorted(window, key=lambda it: -it.expected_amount)


def _late_client_text(plan: "Plan", k: int, gap_size: float) -> str:
    late = [it for it in plan.items if it.direction == "in" and it.delay_prob >= 0.15 and k - 14 <= it.day <= k
            and it.counterparty and it.expected_amount >= 0.2 * gap_size]
    if not late:
        return ""
    it = max(late, key=lambda x: x.expected_amount)
    when = day_month(plan.dates[min(it.day, plan.horizon - 1)])
    return (f" Если {it.counterparty} заплатит позже ({rub(it.expected_amount)} ожидается {when}, "
            f"{source_label(it)}), нехватка будет больше.")


def _gap_reason(state: "ForecastState", plan: "Plan", k: int, p50: np.ndarray, p10: np.ndarray,
                prob: float, thr: float, b: int | None = None, shortfall: float = 0.0) -> str:
    d = plan.dates[k]
    if k == 0 and plan.start_balance < thr:
        txt = f"Остаток уже ниже нуля ({rub(plan.start_balance)}): счёт в овердрафте."
        if state.hist_min_balance < plan.start_balance:
            txt += f" Раньше остаток опускался до {rub(state.hist_min_balance)} — похоже, это лимит овердрафта."
        return txt + " " + _prob_text(prob)
    due = _due_items(plan, k)
    big = [it for it in due if it.expected_amount >= 0.1 * max(1.0, abs(p50[k] - thr))][:2] or due[:1]
    before = p50[k - 1] if k > 0 else plan.start_balance
    if big:
        pays = " и ".join(_pay(it) for it in big)
        must = any(it.category in MANDATORY or it.kind == "tax" for it in big)
        verb = "нужно обязательно заплатить" if must else "нужно заплатить"
        if prob >= GAP_PROBABILITY_LIKELY:
            if before > thr:
                txt = f"{day_month(d)} {verb} {pays}, а к этому дню на счёте ожидается около {rub(before)}."
            else:
                txt = f"{day_month(d)} {verb} {pays}, а денег на счёте к этому дню, скорее всего, уже не останется."
        else:
            txt = (f"{day_month(d)} {verb} {pays}. Обычно денег хватает (к этому дню ожидается около "
                   f"{rub(before)}), но если поступления будут ниже обычного, на этот платёж может не хватить.")
    else:
        txt = (f"В ближайшие {plural_days(k + 1)} расходы больше поступлений: к {day_month(d)} остаток "
               f"может опуститься до {rub(min(p10[k], p50[k]))}.")
    if b is not None and b - k >= 7 and shortfall > 0 and p50[b] < p50[k]:
        txt += (f" Дальше расходы продолжают превышать поступления: к {day_month(plan.dates[b])} "
                f"нехватка может дойти до {rub(shortfall)}.")
    txt += _late_client_text(plan, k, max(1.0, abs(min(p10[k], p50[k]) - thr)))
    return txt + " " + _prob_text(prob)


def _comfort_reason(state: "ForecastState", plan: "Plan", k: int, p50: np.ndarray, prob: float,
                    comfort: float) -> str:
    d = plan.dates[k]
    auto = state.settings.get("comfort_source") == "auto"
    cushion = f"вашей подушки безопасности {rub(comfort)}" + (" (это расходы примерно за 7 дней)" if auto else "")
    txt = (f"{day_month(d)} остаток может опуститься ниже {cushion}: к этому дню ожидается около {rub(p50[k])}. "
           "На платежи денег хватит, но запаса почти не останется.")
    due = _due_items(plan, k)[:1]
    if due:
        txt += f" Рядом с этой датой — {_pay(due[0])}."
    return txt + " " + _prob_text(prob)


def _round_up(x: float) -> float:
    if x <= 0:
        return 0.0
    step = 10_000 if x < 1_000_000 else 100_000
    return math.ceil(x / step) * step


def _recommendations(state: "ForecastState", plan: "Plan", k: int, a: int, b: int, shortfall: float,
                     gap: bool) -> list[str]:
    """2–3 варианта действий владельца. Формулируются как варианты, не как приказ."""
    recs: list[str] = []
    d = plan.dates[k]
    end_ep = plan.dates[b] + timedelta(days=1)
    # 1. попросить клиента оплатить раньше
    incoming = [it for it in plan.items if it.direction == "in" and it.counterparty and it.category == "revenue"
                and k - 5 <= it.day + it.day_shift <= k + 21]
    if incoming:
        it = max(incoming, key=lambda x: x.expected_amount)
        when = plan.dates[min(it.day + it.day_shift, plan.horizon - 1)]
        recs.append(f"Можно попросить {it.counterparty} оплатить {rub(it.expected_amount)} до {day_month(d)} — "
                    f"сейчас оплата ожидается {day_month(when)} ({source_label(it)}).")
    # 2. перенести платёж, который можно перенести (не зарплату и не налоги)
    movable = [it for it in plan.items if it.direction == "out" and it.movable and a - 3 <= it.day + it.day_shift <= b]
    mandatory_near = any((it.category in ("payroll", "taxes") or it.kind == "tax")
                         and a - 3 <= it.day + it.day_shift <= b for it in plan.items)
    if movable:
        it = max(movable, key=lambda x: x.expected_amount)
        what = f"оплату {_what(it)}" if it.category == "suppliers" else _what(it)
        who = f" Для этого нужно договориться об отсрочке с {it.counterparty}." if it.counterparty else ""
        txt = f"Можно перенести {what} ({rub(it.expected_amount)}) на {day_month(end_ep)} или позже.{who}"
        if mandatory_near:
            txt += " Зарплату и налоги лучше не переносить: за просрочку будут штрафы и пени."
        recs.append(txt)
    # 3. заёмные деньги — только как вариант, с суммой и сроком
    if gap and shortfall > 0 and plan.start_balance < 0:
        recs.append(f"Счёт уже в минусе: можно обсудить с банком лимит овердрафта не меньше "
                    f"{rub(_round_up(shortfall))} или вернуть деньги со счетов в других банках.")
    elif gap and shortfall > 0:
        days = max(3, (b - a) + 3)
        recs.append(f"Если перенести платежи не получится, можно рассмотреть овердрафт или кредит примерно на "
                    f"{rub(_round_up(shortfall))} на {plural_days(days)} — заранее сравните стоимость в банке.")
    # 4. мягкие варианты
    if len(recs) < 3:
        recs.append("Можно попросить предоплату у клиентов по новым заказам и выставить счета пораньше.")
    if len(recs) < 2:
        recs.append("Можно отложить необязательные покупки до прихода денег от клиентов.")
    return recs[:3]
