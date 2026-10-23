"""Налоговый календарь: ЕНП до 28-го, авансы по УСН, НДС по кварталам — по параметрам компании.

Режим налогообложения берётся из настроек компании или оценивается по выписке (ядро
``estimate_tax_regime``, иначе — по назначениям платежей). Суммы — оценка по истории:

* **НДФЛ и страховые взносы** (каждый месяц, 28-е) — медиана ЕНП в «обычные» месяцы последнего года;
  если налоговых платежей в истории нет — 42% от средней месячной зарплаты;
* **УСН 6%** — 6% выручки квартала минус уплаченные взносы (не больше 50%), авансы 28.04, 28.07, 28.10,
  годовой — 28.03 (ООО) / 28.04 (ИП);
* **УСН 15%** — 15% от (доходы − расходы), не меньше 1% выручки;
* **ОСНО** — НДС: (НДС с поступлений − НДС с оплат поставщикам) за квартал, тремя равными частями
  28-го в каждый из трёх следующих месяцев; налог на прибыль — авансы 28.04/28.07/28.10, годовой 28.03;
* **ЕСХН** — 6% от (доходы − расходы): аванс 28.07, годовой 28.03.

Срок на выходной переносится на следующий рабочий день (производственный календарь РФ).
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from ..textfmt import MONTHS_NOM, day_month, rub
from .base import CompanyContext, Integration, SourceEvent, next_business_day

REGIME_LABELS = {
    "usn_income": "УСН «Доходы» 6%", "usn_income_expense": "УСН «Доходы минус расходы» 15%",
    "osno": "ОСНО (с НДС)", "eshn": "ЕСХН", "unknown": "режим не определён",
}
_ALIASES = {"usn6": "usn_income", "usn15": "usn_income_expense", "usn": "usn_income", "осно": "osno", "есхн": "eshn"}
_VAT_RX = re.compile(r"(?i)ндс\s*\(?\s*(\d{1,2})\s*%\s*\)?\s*[=:-]?\s*([\d\s ]+[.,]\d{2})")
_NOT_REVENUE = re.compile(r"(?i)собственн|займ|кредит|транш|депозит|возврат|ошибочн|дивиденд")
_PAYROLL_RX = re.compile(r"(?i)заработн|зарплат|\(аванс\)|аванс по заработ")
_TAX_RX = re.compile(r"(?i)енп|единый налог|енс|налог|фнс|страхов")


def _ym(d: date) -> tuple[int, int]:
    return d.year, d.month


def _quarter(y: int, q: int) -> tuple[date, date]:
    start = date(y, 3 * q - 2, 1)
    end = date(y + (q == 4), 1 if q == 4 else 3 * q + 1, 1) - timedelta(days=1)
    return start, end


def _add_months(y: int, m: int, k: int) -> tuple[int, int]:
    t = y * 12 + m - 1 + k
    return t // 12, t % 12 + 1


class TaxCalendar(Integration):
    name = "tax_calendar"
    title = "Налоговый календарь"
    source = "tax_calendar"
    description = "Сроки и оценка сумм ЕНП, авансов по УСН, НДС и налога на прибыль"
    horizon_days = 95

    def regime(self, ctx: CompanyContext) -> dict[str, Any]:
        r = str(ctx.settings.get("tax_regime") or "").lower()
        r = _ALIASES.get(r, r)
        if r in REGIME_LABELS and r != "unknown":
            return {"regime": r, "label": REGIME_LABELS[r], "confidence": 1.0, "evidence": ["указан в настройках компании"]}
        if ctx.core is not None and getattr(ctx.core, "name", "") == "cashflow_core" and len(ctx.df):
            est = ctx.core.tax_regime(ctx.df)
            if est.get("regime") in REGIME_LABELS and est.get("regime") != "unknown":
                return est
        return self._heuristic(ctx)

    def _heuristic(self, ctx: CompanyContext) -> dict[str, Any]:
        df = ctx.df
        if not len(df):
            return {"regime": "unknown", "label": REGIME_LABELS["unknown"], "confidence": 0.0, "evidence": []}
        inc = df[df["direction"] == "in"]
        share_vat = float(inc["purpose"].str.contains(r"(?i)в\s*т\.?\s*ч\.?\s*ндс\s*\(?(?:20|22)", regex=True).mean()) if len(inc) else 0.0
        text = " ".join(df.loc[df["direction"] == "out", "purpose"].astype(str).tolist()).lower()
        if share_vat > 0.3:
            return {"regime": "osno", "label": REGIME_LABELS["osno"], "confidence": 0.6,
                    "evidence": [f"НДС 20–22% выделен в {share_vat:.0%} поступлений"]}
        if "есхн" in text or "сельскохоз" in ctx.industry.lower():
            return {"regime": "eshn", "label": REGIME_LABELS["eshn"], "confidence": 0.5, "evidence": ["отрасль/назначения"]}
        if "15%" in text or "доходы минус расходы" in text:
            return {"regime": "usn_income_expense", "label": REGIME_LABELS["usn_income_expense"], "confidence": 0.5, "evidence": []}
        return {"regime": "usn_income", "label": REGIME_LABELS["usn_income"], "confidence": 0.4,
                "evidence": ["НДС в поступлениях не выделен — вероятнее упрощёнка"]}

    # ------------------------------------------------------------------ оценки по истории
    def _series(self, ctx: CompanyContext) -> dict[str, Any]:
        cat = ctx.categories()
        d = cat.copy()
        d["date"] = pd.to_datetime(d["date"]).dt.date
        text = d["purpose"].astype(str) + " " + d["counterparty_name"].astype(str)
        if "category" in d.columns and d["category"].isin(["revenue", "taxes"]).any():
            is_rev = (d["direction"] == "in") & (d["category"] == "revenue")
            is_tax = (d["direction"] == "out") & (d["category"] == "taxes")
            is_pay = (d["direction"] == "out") & (d["category"] == "payroll")
            is_exp = (d["direction"] == "out") & ~d["category"].isin(["taxes", "transfers", "loans"])
        else:
            is_rev = (d["direction"] == "in") & ~text.str.contains(_NOT_REVENUE)
            is_tax = (d["direction"] == "out") & text.str.contains(_TAX_RX)
            is_pay = (d["direction"] == "out") & text.str.contains(_PAYROLL_RX)
            is_exp = (d["direction"] == "out") & ~is_tax & ~text.str.contains(_NOT_REVENUE)
        own = d["counterparty_inn"].astype(str).eq(ctx.inn) if ctx.inn else False
        is_rev = is_rev & ~own

        def vat_amounts(mask: pd.Series) -> pd.Series:
            vals = []
            for p, a in zip(d.loc[mask, "purpose"].astype(str), d.loc[mask, "amount"]):
                m = _VAT_RX.search(p)
                v = 0.0
                if m:
                    try:
                        v = float(m.group(2).replace(" ", "").replace(" ", "").replace(",", "."))
                    except ValueError:
                        v = 0.0
                    if not 0 < v < a:
                        v = a * int(m.group(1)) / (100 + int(m.group(1)))
                vals.append(v)
            return pd.Series(vals, index=d.index[mask], dtype=float)

        return {"d": d, "rev": d[is_rev], "tax": d[is_tax], "pay": d[is_pay], "exp": d[is_exp],
                "vat_out": pd.concat([d.loc[is_rev, ["date"]], vat_amounts(is_rev).rename("vat")], axis=1),
                "vat_in": pd.concat([d.loc[is_exp, ["date"]], vat_amounts(is_exp).rename("vat")], axis=1)}

    @staticmethod
    def _sum_between(frame: pd.DataFrame, col: str, a: date, b: date) -> float:
        if not len(frame):
            return 0.0
        m = (frame["date"] >= a) & (frame["date"] <= b)
        return float(frame.loc[m, col].sum())

    def _quarter_value(self, frame: pd.DataFrame, col: str, y: int, q: int, as_of: date, first: date) -> tuple[float, str]:
        """Сумма за квартал; незаконченный квартал — экстраполяция, нет истории — тот же квартал год назад."""
        a, b = _quarter(y, q)
        if a < first and b < first:
            pa, pb = _quarter(y - 1, q)
            return self._sum_between(frame, col, pa, pb), "по тому же кварталу прошлого года"
        lo = max(a, first)
        hi = min(b, as_of)
        if hi < lo:
            return 0.0, ""
        v = self._sum_between(frame, col, lo, hi)
        covered = (hi - lo).days + 1
        total = (b - a).days + 1
        if covered < total * 0.95:
            return v * total / max(covered, 1), "квартал не закончился — оценка по темпу"
        return v, ""

    def _base(self, s: dict[str, Any], as_of: date, regime: str, first: date) -> tuple[float, str]:
        """НДФЛ и взносы в месяц: медиана ЕНП за год в месяцы без квартальных платежей
        (у плательщика НДС — за вычетом трети НДС прошлого квартала); без истории — 41% от зарплаты
        (медиана по датасету организаторов)."""
        tax = s["tax"]
        last_year = tax[tax["date"] > as_of - timedelta(days=365)]
        if len(last_year) >= 3:
            by = last_year.groupby(last_year["date"].map(_ym))["amount"].sum()
            vals = []
            for (y, m), v in by.items():
                if m in (1, 3, 4, 7, 10):
                    continue
                if regime == "osno":
                    q = (y - 1, 4) if m <= 3 else (y, (m - 1) // 3)
                    vo, _ = self._quarter_value(s["vat_out"], "vat", *q, as_of, first)
                    vi, _ = self._quarter_value(s["vat_in"], "vat", *q, as_of, first)
                    v -= max(vo - vi, 0.0) / 3
                vals.append(v)
            if len(vals) >= 3 and float(np.median(vals)) > 0:
                return float(np.median(vals)), "медиана ЕНП за год"
        pay = s["pay"]
        if len(pay):
            recent = pay[pay["date"] > as_of - timedelta(days=92)]
            months = max(1, len({_ym(x) for x in recent["date"]}))
            return 0.41 * float(recent["amount"].sum()) / months, "41% от средней зарплаты"
        return 0.0, ""

    # ------------------------------------------------------------------ календарь
    def fetch(self, company: CompanyContext) -> list[SourceEvent]:
        ctx = company
        if not len(ctx.df) or ctx.as_of is None:
            return []
        reg = self.regime(ctx)
        regime = reg.get("regime", "unknown")
        if regime == "unknown":
            regime = "usn_income"
        s = self._series(ctx)
        as_of = ctx.as_of
        first = min(s["d"]["date"])
        base, base_how = self._base(s, as_of, regime, first)
        is_ip = ctx.legal_form.upper() == "ИП" or ctx.name.upper().startswith("ИП ")
        events: list[SourceEvent] = []
        end = as_of + timedelta(days=self.horizon_days)
        y, m = as_of.year, as_of.month
        while True:
            due = next_business_day(date(y, m, 28))
            if due > end:
                break
            if due > as_of:
                parts: list[tuple[str, float]] = []
                py, pm = _add_months(y, m, -1)
                if base > 0:
                    parts.append((f"НДФЛ и страховые взносы за {MONTHS_NOM[pm - 1]}", base))
                parts += self._regime_parts(regime, y, m, s, as_of, first, base, is_ip)
                total = round(sum(v for _, v in parts), -2)
                if total > 0:
                    txt = "; ".join(f"{name} ≈ {rub(v)}" for name, v in parts if v > 0)
                    note = (f"ЕНП до {day_month(due)}: {txt}. Оценка по выписке, {reg.get('label', REGIME_LABELS[regime])}"
                            + (f" (уверенность {float(reg.get('confidence', 0)):.0%})" if reg.get("confidence") else "") + ".")
                    events.append(SourceEvent(
                        id=f"tax-{due.isoformat()}", type="tax", direction="out", amount=float(total), date=due,
                        source="tax_calendar", status="expected", counterparty="ФНС России (ЕНП)", note=note))
            y, m = _add_months(y, m, 1)
        return events

    def _regime_parts(self, regime: str, y: int, m: int, s: dict[str, Any], as_of: date, first: date, base: float,
                      is_ip: bool) -> list[tuple[str, float]]:
        parts: list[tuple[str, float]] = []
        rev, exp = s["rev"], s["exp"]
        q_prev = (y - 1, 4) if m <= 3 else (y, (m - 1) // 3)       # квартал, который закончился до этого месяца
        if regime == "usn_income":
            if m in (4, 7, 10) or (m == (4 if is_ip else 3)):
                qy, qn = (y, (m - 1) // 3) if m in (4, 7, 10) else (y - 1, 4)
                r, how = self._quarter_value(rev, "amount", qy, qn, as_of, first)
                tax = 0.06 * r
                tax -= min(3 * base * 0.75, 0.5 * tax)               # уменьшение на взносы (до 50%)
                label = {1: "1 квартал", 2: "полугодие", 3: "9 месяцев", 4: f"{qy} год"}[qn]
                parts.append((f"УСН 6% за {label} (выручка за {qn} кв. ≈ {rub(r)}{', ' + how if how else ''})", max(tax, 0.0)))
        elif regime == "usn_income_expense":
            if m in (4, 7, 10) or (m == (4 if is_ip else 3)):
                qy, qn = (y, (m - 1) // 3) if m in (4, 7, 10) else (y - 1, 4)
                r, _ = self._quarter_value(rev, "amount", qy, qn, as_of, first)
                e, _ = self._quarter_value(exp, "amount", qy, qn, as_of, first)
                tax = max(0.15 * (r - e), 0.01 * r)
                parts.append((f"УСН 15% за {qn} кв. (доходы {rub(r)} − расходы {rub(e)})", tax))
        elif regime == "osno":
            vo, _ = self._quarter_value(s["vat_out"], "vat", *q_prev, as_of, first)
            vi, _ = self._quarter_value(s["vat_in"], "vat", *q_prev, as_of, first)
            if vo <= 0:
                r, _ = self._quarter_value(rev, "amount", *q_prev, as_of, first)
                rate = 22 if q_prev[0] >= 2026 else 20
                vo = r * rate / (100 + rate)
            vat = max(vo - vi, 0.0) / 3
            if vat > 0:
                parts.append((f"НДС за {q_prev[1]} кв. {q_prev[0]} (1/3)", vat))
            if m in (3, 4, 7, 10):
                qy, qn = (y - 1, 4) if m == 3 else (y, (m - 1) // 3)
                r, _ = self._quarter_value(rev, "amount", qy, qn, as_of, first)
                e, _ = self._quarter_value(exp, "amount", qy, qn, as_of, first)
                rate = 22 if qy >= 2026 else 20
                rev_ex = r - vo if 0 < vo < r else r / (1 + rate / 100)     # выручка без НДС
                # расходы без НДС + НДФЛ и взносы (часть начисленной зарплаты); маржа не выше 15%
                profit = min(max(rev_ex - e / 1.15 - 3 * base, 0.0), 0.15 * rev_ex)
                parts.append(("налог на прибыль" + (" за год" if m == 3 else f" (аванс за {qn} кв.)"), 0.25 * profit))
        elif regime == "eshn":
            if m in (7, 3):
                halves = [(y, 1), (y, 2)] if m == 7 else [(y - 1, 3), (y - 1, 4)]
                r = sum(self._quarter_value(rev, "amount", qy, qn, as_of, first)[0] for qy, qn in halves)
                e = sum(self._quarter_value(exp, "amount", qy, qn, as_of, first)[0] for qy, qn in halves)
                parts.append(("ЕСХН 6% " + ("аванс за полугодие" if m == 7 else "за год"), max(0.06 * (r - e), 0.0)))
        return parts

    def message(self, company: CompanyContext, events: list[SourceEvent]) -> str:
        reg = self.regime(company)
        return f"Режим: {reg.get('label')}. Сроков в ближайшие 3 месяца: {len(events)}."
