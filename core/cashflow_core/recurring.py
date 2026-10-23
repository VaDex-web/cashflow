"""Поиск регулярных платежей (п.3 задания).

Операции группируются по контрагенту + направлению + категории; для зарплаты
и налогов — по категории целиком (зарплата часто уходит десятку сотрудников
в один день, это один «платёж»). Внутри группы суммы сворачиваются по датам.

Для каждой группы ищутся «якоря»:

* **monthly** — день месяца ``a``: в ≥70% месяцев есть платёж в пределах
  ±4 дней от ``a`` с учётом переноса с выходных/праздников. До двух якорей
  на группу — так аванс и зарплата (10-е и 25-е) становятся двумя паттернами;
* **weekly / biweekly** — день недели, платёж в ≥70% недель;
* **quarterly** — шаг ~91 день.

Плотные потоки (эквайринг каждый день) не считаются регулярными платежами —
их моделирует стохастическая часть прогноза.

Уверенность = число повторов × точность дат × стабильность суммы × покрытие периодов.
"""
from __future__ import annotations

import calendar
import hashlib
import re
from functools import lru_cache
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from .calendar_ru import is_business_day, shift_to_business_day
from .log import get_logger
from .schema import CATEGORIES

log = get_logger(__name__)

#: Категории, которые группируются целиком (без разбивки по контрагентам).
AGGREGATE_CATEGORIES = ("payroll", "taxes")
#: Категории, где регулярность не ищем (переводы самому себе непредсказуемы по смыслу).
SKIP_CATEGORIES = ("transfers",)
MIN_CONFIDENCE = 0.3

_DEFAULT_SHIFT = {"payroll": "backward", "taxes": "forward"}


def _month_index(d: date) -> int:
    return d.year * 12 + d.month - 1


@lru_cache(maxsize=50000)
def _nominal(year: int, month: int, anchor: int) -> date:
    return date(year, month, min(anchor, calendar.monthrange(year, month)[1]))


def _from_month_index(mi: int, anchor: int) -> date:
    return _nominal(mi // 12, mi % 12 + 1, anchor)


@dataclass
class RecurringPattern:
    """Найденный регулярный платёж с расписанием."""

    key: str
    name: str
    direction: str
    category: str
    kind: str                      # weekly | biweekly | monthly | quarterly
    period_days: int
    anchor: int                    # день месяца (monthly/quarterly) или день недели (weekly)
    shift_rule: str                # backward | forward
    amounts: list[float]
    dates: list[date]
    last_nominal: date
    counterparty: str = ""
    counterparty_inn: str = ""
    group_key: str = ""
    confidence: float = 0.0
    late_share: float = 0.0        # доля платежей, пришедших позже ожидаемого > 3 дн.
    timing_mad: float = 0.0
    tx_ids: list[str] = field(default_factory=list)

    # ------------------------------------------------------------ amounts
    @property
    def amount_forecast(self) -> float:
        """Сумма для прогноза — медиана последних 3 платежей (учитывает рост зарплаты и т.п.).

        Для налогов — медиана за год: квартальные всплески ЕНП моделирует :mod:`taxes`.
        """
        if not self.amounts:
            return 0.0
        k = 12 if self.category == "taxes" else 3
        return float(np.median(self.amounts[-k:]))

    @property
    def amount_avg(self) -> float:
        return float(np.mean(self.amounts[-6:])) if self.amounts else 0.0

    @property
    def amount_cv(self) -> float:
        a = np.array(self.amounts[-6:], dtype=float)
        if len(a) < 2 or a.mean() <= 0:
            return 0.3
        return float(min(1.0, a.std(ddof=1) / a.mean()))

    # ------------------------------------------------------------ schedule
    def _expected_after(self, nominal: date) -> date:
        return shift_to_business_day(nominal, self.shift_rule)  # type: ignore[arg-type]

    def schedule(self, until: date, max_items: int = 400) -> list[tuple[date, date]]:
        """Ожидаемые (номинальная, фактическая) даты после последнего платежа и до ``until`` включительно."""
        out: list[tuple[date, date]] = []
        if self.kind in ("monthly", "quarterly"):
            step = 1 if self.kind == "monthly" else 3
            mi = _month_index(self.last_nominal) + step
            while len(out) < max_items:
                nom = _from_month_index(mi, self.anchor)
                exp = self._expected_after(nom)
                if exp > until:
                    break
                out.append((nom, exp))
                mi += step
        else:
            nom = self.last_nominal + timedelta(days=self.period_days)
            while len(out) < max_items:
                exp = self._expected_after(nom)
                if exp > until:
                    break
                out.append((nom, exp))
                nom += timedelta(days=self.period_days)
        return out

    def next_date(self, as_of: date) -> date | None:
        """Ближайшая ожидаемая дата (если платёж уже «просрочен» — следующий день после as_of)."""
        sch = self.schedule(as_of + timedelta(days=self.period_days * 2 + 10))
        if not sch:
            return None
        exp = sch[0][1]
        return max(exp, as_of + timedelta(days=1))

    def is_active(self, as_of: date) -> bool:
        """Паттерн активен, если пропущено не больше одного периода (+допуск)."""
        sch = self.schedule(as_of)
        if not sch:
            return True
        grace = max(7, int(self.period_days * 0.5))
        missed = [e for _, e in sch if (as_of - e).days > grace]
        return len(missed) == 0

    def register_payment(self, d: date, amount: float, tx_id: str = "") -> None:
        """Учесть новый фактический платёж (для инкрементального обновления)."""
        sch = self.schedule(d + timedelta(days=10))
        if sch:
            nom = min(sch, key=lambda ne: abs((ne[1] - d).days))[0]
            self.last_nominal = max(self.last_nominal, nom)
        self.dates.append(d)
        self.amounts.append(float(amount))
        if tx_id:
            self.tx_ids.append(tx_id)

    def to_contract(self, as_of: date) -> dict[str, Any]:
        """Словарь в формате контракта: {name, direction, amount_avg, period_days, next_date, confidence}."""
        nd = self.next_date(as_of)
        return {
            "name": self.name,
            "direction": self.direction,
            "amount_avg": round(self.amount_avg, 2),
            "period_days": int(self.period_days),
            "next_date": nd.isoformat() if nd else None,
            "confidence": round(float(self.confidence), 3),
        }


# --------------------------------------------------------------------------- detection helpers
@lru_cache(maxsize=200000)
def _offset(d: date, nominal: date) -> int:
    """Минимальное расстояние от фактической даты до номинальной с учётом переноса в обе стороны."""
    cands = [nominal, shift_to_business_day(nominal, "forward"), shift_to_business_day(nominal, "backward")]
    best = min(cands, key=lambda c: abs((d - c).days))
    return (d - best).days


def _assign_monthly(dates: list[date], anchor: int, tol: int = 4) -> dict[int, int]:
    """Сопоставить датам месяцы при якоре ``anchor``. Возвращает {month_index: index даты}."""
    best: dict[int, tuple[int, int]] = {}
    for i, d in enumerate(dates):
        for mi in (_month_index(d) - 1, _month_index(d), _month_index(d) + 1):
            nom = _from_month_index(mi, anchor)
            off = abs(_offset(d, nom))
            if off <= tol and (mi not in best or off < best[mi][1]):
                best[mi] = (i, off)
    # одна дата — один месяц
    used: dict[int, tuple[int, int]] = {}
    for mi, (i, off) in sorted(best.items(), key=lambda kv: kv[1][1]):
        if i in {v[0] for v in used.values()}:
            continue
        used[mi] = (i, off)
    return {mi: v[0] for mi, v in used.items()}


def _shift_rule(dates: list[date], noms: list[date], category: str) -> str:
    back = fwd = 0
    for d, n in zip(dates, noms):
        if not is_business_day(n):
            if d < n:
                back += 1
            elif d > n:
                fwd += 1
    if back == fwd:
        return _DEFAULT_SHIFT.get(category, "forward")
    return "backward" if back > fwd else "forward"


def _confidence(n: int, offsets: list[int], amounts: list[float], coverage: float) -> float:
    n_f = 1 - np.exp(-(n - 1) / 2.5)
    mad = float(np.mean(np.abs(offsets))) if offsets else 3.0
    timing = float(np.exp(-mad / 4.0))
    a = np.array(amounts[-6:], dtype=float)
    cv = float(a.std(ddof=1) / a.mean()) if len(a) > 1 and a.mean() > 0 else 0.5
    amount = float(np.exp(-1.2 * cv))
    return float(np.clip(np.sqrt(n_f) * timing * np.sqrt(amount) * min(1.0, coverage / 0.9), 0, 0.99))


def _detect_monthly(dates: list[date], amounts: list[float], as_of: date, category: str,
                    max_anchors: int = 2) -> list[dict[str, Any]]:
    """Найти до ``max_anchors`` месячных якорей в ряду дат."""
    found: list[dict[str, Any]] = []
    remaining = list(range(len(dates)))
    for _ in range(max_anchors):
        if len(remaining) < 3:
            break
        sub = [dates[i] for i in remaining]
        best = None
        for a in range(1, 32):
            assign = _assign_monthly(sub, a)
            if len(assign) < 3:
                continue
            mis = sorted(assign)
            span = _month_index(as_of) - mis[0] + 1
            # последний месяц может быть ещё «не наступил»
            nom_last = _from_month_index(_month_index(as_of), a)
            if shift_to_business_day(nom_last, "forward") > as_of and _month_index(as_of) not in assign:
                span -= 1
            coverage = len(assign) / max(span, 1)
            offs = [abs(_offset(sub[assign[m]], _from_month_index(m, a))) for m in mis]
            score = len(assign) * coverage - 0.15 * float(np.mean(offs))
            if best is None or score > best[0]:
                best = (score, a, assign, coverage, offs)
        if best is None or best[3] < 0.7:
            break
        _, a, assign, coverage, offs = best
        idx = [remaining[assign[m]] for m in sorted(assign)]
        found.append({"anchor": a, "idx": idx, "coverage": coverage, "offsets": offs,
                      "noms": [_from_month_index(m, a) for m in sorted(assign)]})
        remaining = [i for i in remaining if i not in set(idx)]
    return found


def _detect_weekly(dates: list[date], as_of: date, period: int) -> dict[str, Any] | None:
    if len(dates) < 4:
        return None
    span_weeks = max(1, ((as_of - dates[0]).days + 1) / period)
    if len(dates) / span_weeks > 1.6:  # слишком плотно — это поток, а не платёж
        return None
    iv = np.diff([d.toordinal() for d in dates])
    if not len(iv):
        return None
    med = float(np.median(iv))
    tol = 1.5 if period == 7 else 2.5
    good = np.abs(iv - period) <= tol
    if abs(med - period) > tol or good.mean() < 0.7:
        return None
    coverage = min(1.0, len(dates) / span_weeks)
    if coverage < 0.6:
        return None
    offs = list((iv - period).astype(int))
    return {"anchor": dates[-1].weekday(), "coverage": coverage, "offsets": offs}


def _detect_quarterly(dates: list[date], as_of: date) -> dict[str, Any] | None:
    if len(dates) < 3:
        return None
    iv = np.diff([d.toordinal() for d in dates])
    good = np.abs(iv - 91) <= 12
    if good.mean() < 0.75:
        return None
    span_q = max(1, ((as_of - dates[0]).days + 1) / 91)
    coverage = min(1.0, len(dates) / span_q)
    if coverage < 0.7:
        return None
    return {"anchor": int(np.median([d.day for d in dates])), "coverage": coverage,
            "offsets": list((iv - 91).astype(int))}


def _cp_key(inn: str, name: str) -> str:
    inn = (inn or "").strip()
    if inn:
        return "inn:" + inn
    n = re.sub(r"\s+", " ", (name or "").lower()).strip()
    return "name:" + n if n else ""


def _pattern_name(category: str, counterparty: str, kind: str, anchor: int, n_anchors: int) -> str:
    label = CATEGORIES.get(category, category)
    cp = f" — {counterparty}" if counterparty and category not in AGGREGATE_CATEGORIES else ""
    when = {"weekly": "еженедельно", "biweekly": "раз в 2 недели", "quarterly": "ежеквартально"}.get(kind, "")
    if kind == "monthly":
        when = f"~{anchor}-го числа" if anchor < 31 else "в конце месяца"
    return f"{label}{cp} ({when})"


# --------------------------------------------------------------------------- main API
def find_patterns(df: pd.DataFrame, as_of: date | None = None, *, min_confidence: float = MIN_CONFIDENCE,
                  active_only: bool = True) -> list[RecurringPattern]:
    """Найти регулярные платежи. ``df`` — категоризированная выписка.

    Args:
        as_of: дата «сегодня» (по умолчанию — последняя дата выписки).
        min_confidence: минимальная уверенность паттерна.
        active_only: отбрасывать прекратившиеся паттерны.
    """
    if df is None or not len(df) or "category" not in df.columns:
        return []
    d = df.copy()
    d.attrs = {}
    d["date"] = pd.to_datetime(d["date"]).dt.date
    as_of = as_of or max(d["date"])
    d = d[~d["category"].isin(SKIP_CATEGORIES)]
    d["cp"] = [_cp_key(i, n) for i, n in zip(d["counterparty_inn"], d["counterparty_name"])]
    d["gkey"] = np.where(d["category"].isin(AGGREGATE_CATEGORIES), "cat:" + d["category"], d["cp"])
    d = d[d["gkey"] != ""]
    patterns: list[RecurringPattern] = []

    for (gkey, direction, category), g in d.groupby(["gkey", "direction", "category"], sort=False):
        per_day = g.groupby("date").agg(amount=("amount", "sum"), ids=("tx_id", list)).sort_index()
        dates = list(per_day.index)
        amounts = per_day["amount"].astype(float).tolist()
        if len(dates) < 3:
            continue
        cp_name = g["counterparty_name"].mode().iloc[0] if g["counterparty_name"].ne("").any() else ""
        cp_inn = g["counterparty_inn"].mode().iloc[0] if g["counterparty_inn"].ne("").any() else ""
        months_span = max(1, _month_index(as_of) - _month_index(dates[0]) + 1)
        density = len(dates) / months_span
        candidates: list[tuple[str, int, dict[str, Any], list[int]]] = []

        if density <= 2.6:
            for m in _detect_monthly(dates, amounts, as_of, category):
                candidates.append(("monthly", 30, m, m["idx"]))
        if not candidates:
            for period, kind in ((7, "weekly"), (14, "biweekly")):
                w = _detect_weekly(dates, as_of, period)
                if w:
                    candidates.append((kind, period, w, list(range(len(dates)))))
                    break
        if not candidates and density <= 0.6 and category != "taxes":  # квартальные налоги — в taxes.py
            q = _detect_quarterly(dates, as_of)
            if q:
                candidates.append(("quarterly", 91, q, list(range(len(dates)))))

        group_assigned = {dates[i] for _, _, _, ix in candidates for i in ix}
        for kind, period, info, idx in candidates:
            pd_dates = [dates[i] for i in idx]
            pd_amts = [amounts[i] for i in idx]
            if kind == "monthly":
                noms = info["noms"]
                rule = _shift_rule(pd_dates, noms, category)
                last_nom = noms[-1]
            else:
                rule = "forward"
                noms = pd_dates
                last_nom = pd_dates[-1]
            conf = _confidence(len(pd_dates), info["offsets"], pd_amts, info["coverage"])
            offs = info["offsets"]
            late = float(np.mean([o > 3 for o in offs])) if offs else 0.0
            key_src = f"{gkey}|{direction}|{category}|{kind}|{info['anchor']}"
            pat = RecurringPattern(
                key="r" + hashlib.sha1(key_src.encode()).hexdigest()[:10],
                name=_pattern_name(category, cp_name, kind, info["anchor"], len(candidates)),
                direction=str(direction), category=str(category), kind=kind, period_days=period,
                anchor=int(info["anchor"]), shift_rule=rule, amounts=pd_amts, dates=pd_dates,
                last_nominal=last_nom, counterparty=str(cp_name), counterparty_inn=str(cp_inn),
                group_key=str(gkey), confidence=conf, late_share=late,
                timing_mad=float(np.mean(np.abs(offs))) if offs else 0.0,
                tx_ids=[t for i in idx for t in per_day["ids"].iloc[i]],
            )
            # Платёж текущего периода мог прийти заметно раньше срока (ЕНП 18-го вместо 28-го):
            # если в группе есть неучтённый платёж похожей суммы — считаем период оплаченным.
            sch = pat.schedule(as_of + timedelta(days=period))
            if sch:
                exp = sch[0][1]
                window = 20 if kind in ("monthly", "quarterly") else 3
                ref = pat.amount_forecast
                for i, dd in enumerate(dates):
                    if (dd > pd_dates[-1] and dd not in group_assigned and exp - timedelta(days=window) <= dd <= as_of
                            and ref > 0 and 0.5 <= amounts[i] / ref <= 1.6):
                        pat.register_payment(dd, amounts[i])
                        pat.tx_ids.extend(per_day["ids"].iloc[i])
                        group_assigned.add(dd)
                        break
            if pat.confidence >= min_confidence and (not active_only or pat.is_active(as_of)):
                patterns.append(pat)

    patterns.sort(key=lambda p: (-p.amount_forecast * (30 / p.period_days), p.name))
    log.info("recurring patterns found: %d", len(patterns))
    return patterns


def inactive_patterns(df: pd.DataFrame, as_of: date | None = None) -> list[RecurringPattern]:
    """Паттерны, которые раньше были регулярными, но прекратились (например, ушёл клиент)."""
    if df is None or not len(df) or "category" not in df.columns:
        return []
    as_of = as_of or pd.to_datetime(df["date"]).max().date()
    return [p for p in find_patterns(df, as_of, min_confidence=0.5, active_only=False) if not p.is_active(as_of)]


def detect_recurring(df: pd.DataFrame, as_of: date | None = None) -> list[dict[str, Any]]:
    """Публичный API контракта: список регулярных платежей.

    Returns:
        ``[{name, direction, amount_avg, period_days, next_date, confidence}]`` —
        отсортировано по месячному объёму.
    """
    if df is not None and len(df) and "category" not in df.columns:
        from .categorize import categorize

        df = categorize(df)
    if df is None or not len(df):
        return []
    as_of = as_of or pd.to_datetime(df["date"]).max().date()
    return [p.to_contract(as_of) for p in find_patterns(df, as_of)]
